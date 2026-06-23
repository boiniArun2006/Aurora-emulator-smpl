#!/usr/bin/env python3
"""
Aurora Emulator - Phase 1: AOT Texture Transcoder
==================================================

This module implements the "Texture Engine" of the Aurora emulator's AOT
preprocessing pipeline. The core idea:

    PC game ships with .dds textures (BC1/BC3/BC5/BC7 format)
        |  [AOT preprocessing - done ONCE on game install]
        v
    Decode BCn -> raw RGBA
        |
        v
    Re-encode as KTX2 with UASTC codec (supercompressed interchange format)
        |  [Storage format on device]
        v
    KTX2/UASTC file (~3-4 bits/pixel)
        |  [On-device transcode - done at load time, microseconds per block]
        v
    ASTC 4x4 LDR (mobile GPU native format, supported by Mali/Adreno)
        |
        v
    Upload to GPU

The expensive step (BCn decode + UASTC encode) happens ONCE at install time.
The cheap step (UASTC -> ASTC transcode) happens at load time, and is fast
enough to do per-texture on demand.

This is the architecture recommended by the Basis Universal project
(https://github.com/BinomialLLC/basis_universal) and validated by the
Khronos KTX2 sample.

Usage:
    python3 aot_texture_transcoder.py <input_dir> <output_dir> [--quality max|fast]

Inputs accepted:
    .png, .jpg, .tga, .qoi  (via basisu's built-in loaders)
    .dds                     (BC1/BC3/BC5/BC7 - via tiny_dds in basisu)
    .exr, .hdr               (HDR - via tinyexr)

Outputs:
    <name>.ktx2              (KTX2 container with UASTC codec inside)
    <name>.astc              (ASTC 4x4 LDR transcoded format, ready for GPU)
    <name>.meta.json         (timing, sizes, source format info)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# =============================================================================
# Configuration
# =============================================================================

# Path to the basisu CLI tool built from Basis Universal source.
# On Windows the binary is basisu.exe, on Linux/macOS it's basisu.
# Build instructions: see third_party/basis_universal/README.md
import sys as _sys
_BASISU_NAME = "basisu.exe" if _sys.platform == "win32" else "basisu"
BASISU_BIN = Path(__file__).resolve().parents[2] / "third_party" / "basis_universal" / "bin" / _BASISU_NAME

# UASTC quality levels (from Basis Universal docs).
# Higher = better quality, slower encode. AOT step can afford higher quality.
UASTC_QUALITY_LEVELS = {
    "fast": 1,    # Fastest encode, lowest quality
    "default": 2, # Default balance
    "max": 5,     # Maximum quality, slowest encode
}

# ASTC block size for the on-device transcode step.
# 4x4 = highest quality, 8 bits/pixel - for high-end devices
# 6x6 = balanced, 3.56 bits/pixel - for mid-range
# 8x8 = lowest quality, 2 bits/pixel - for low-end
# We default to 4x4 because it's universally supported on Mali-G610+ and Adreno 6xx+.
ASTC_BLOCK_SIZE = "4x4"

# Supported input file extensions (matched case-insensitively)
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".qoi", ".dds", ".exr", ".hdr"}

# Valid ASTC block sizes (per ASTC spec)
VALID_ASTC_BLOCK_SIZES = {
    "4x4", "5x4", "5x5", "6x5", "6x6", "8x5", "8x6", "8x8",
    "10x5", "10x6", "10x8", "10x10", "12x10", "12x12",
}


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class TextureResult:
    """Result of processing a single texture through the AOT pipeline."""
    source_file: str
    source_format: str
    source_size_bytes: int
    raw_rgba_bytes: int        # Uncompressed RGBA byte count (W*H*4)

    ktx2_file: str
    ktx2_size_bytes: int
    ktx2_encode_time_ms: float

    astc_file: str
    astc_size_bytes: int
    astc_transcode_time_ms: float

    compression_ratio: float  # raw_rgba / ktx2_size (the meaningful ratio)
    transcode_overhead: float # astc_size / ktx2_size


# =============================================================================
# Core pipeline
# =============================================================================

class AOTTextureTranscoder:
    """Orchestrates the AOT texture preprocessing pipeline.

    Args:
        basisu_bin: Path to the basisu CLI binary.
        quality: UASTC encoding quality ("fast", "default", or "max").
        astc_block_size: ASTC block size for on-device transcode (e.g. "4x4", "6x6").
        single_threaded: If True, disable basisu's internal multithreading.
            ONLY use for benchmarking - production should leave False for speed.
    """

    def __init__(
        self,
        basisu_bin: Path = BASISU_BIN,
        quality: str = "default",
        astc_block_size: str = ASTC_BLOCK_SIZE,
        single_threaded: bool = False,
    ):
        if not basisu_bin.exists():
            raise FileNotFoundError(
                f"basisu binary not found at {basisu_bin}. "
                f"Build it first with: cd third_party/basis_universal && mkdir build && "
                f"cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)"
            )
        if quality not in UASTC_QUALITY_LEVELS:
            raise ValueError(f"quality must be one of {list(UASTC_QUALITY_LEVELS)}, got {quality!r}")
        if astc_block_size not in VALID_ASTC_BLOCK_SIZES:
            raise ValueError(
                f"astc_block_size must be one of {sorted(VALID_ASTC_BLOCK_SIZES)}, "
                f"got {astc_block_size!r}"
            )
        self.basisu = str(basisu_bin)
        self.uastc_level = UASTC_QUALITY_LEVELS[quality]
        self.astc_block_size = astc_block_size
        self.single_threaded = single_threaded

    def detect_source_format(self, src_path: Path) -> str:
        """Detect the source texture format from file extension."""
        ext = src_path.suffix.lower()
        return {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".tga": "TGA",
            ".qoi": "QOI",
            ".dds": "DDS (BCn)",
            ".exr": "EXR (HDR)",
            ".hdr": "HDR (Radiance)",
        }.get(ext, "UNKNOWN")

    def encode_to_ktx2_uastc(
        self, src_path: Path, out_path: Path
    ) -> tuple[float, int]:
        """
        Encode source texture to KTX2 container with UASTC codec.
        This is the expensive step - done ONCE on install.
        """
        if not src_path.exists():
            raise FileNotFoundError(f"Source texture not found: {src_path}")
        if src_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported texture format: {src_path.suffix} "
                f"(supported: {sorted(SUPPORTED_EXTENSIONS)})"
            )

        cmd = [
            self.basisu,
            str(src_path),
            "-ktx2",
            "-uastc",                    # Use UASTC codec (high quality)
            "-uastc_level", str(self.uastc_level),
            "-uastc_rdo_l", "1.0",       # Rate-distortion optimization
            "-mipmap",                   # Generate mipmaps
            "-mip_scale", "1.0",
            "-ktx2_zstandard_level", "9",  # Zstd supercompression level (default=on)
        ]
        if self.single_threaded:
            # ONLY for benchmarking - slows down encoding by ~2-4x
            cmd.append("-no_multithreading")
        cmd.extend(["-output_file", str(out_path)])
        t0 = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True, text=True)
        t1 = time.perf_counter()
        if result.returncode != 0:
            raise RuntimeError(
                f"basisu encode failed for {src_path}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        encode_ms = (t1 - t0) * 1000.0
        size = out_path.stat().st_size
        return encode_ms, size

    def transcode_to_astc(
        self, ktx2_path: Path, out_path: Path, block_size: str | None = None
    ) -> tuple[float, int]:
        """
        Transcode KTX2/UASTC to .astc file (mobile GPU native format).
        This is the fast step - done at load time on the device.
        Basis Universal's transcoder is designed to be near-instant per block.

        Note: On the actual device, this would be a library call to
        basisu_transcoder.cpp (single-file, no deps) - NOT a subprocess.
        We use the CLI here for PoC demonstration only.

        Args:
            ktx2_path: Input KTX2/UASTC file path.
            out_path: Output .astc file path.
            block_size: ASTC block size (e.g. "4x4", "6x6"). Defaults to
                self.astc_block_size. NOTE: The basisu CLI's -unpack mode
                always produces ASTC 4x4 (because UASTC is 4x4 internally);
                to get other block sizes you must re-encode with -ldr_NxN.
                This parameter is validated but currently informational.
        """
        if not ktx2_path.exists():
            raise FileNotFoundError(f"KTX2 input not found: {ktx2_path}")
        bs = block_size or self.astc_block_size
        if bs not in VALID_ASTC_BLOCK_SIZES:
            raise ValueError(f"Invalid ASTC block size: {bs!r}")

        # The basisu CLI's -unpack mode produces ALL supported formats at once
        # (BC1/BC3/BC7/ETC1/ETC2/PVRTC/ASTC). In production we'd link the
        # transcoder library directly and call basist::transcode_astc() to
        # only produce the ASTC output we need. For PoC we use the CLI and
        # pick the ASTC file out of the output set.
        out_dir = out_path.parent
        work_dir = out_dir / f"_unpack_tmp_{ktx2_path.stem}"

        # BUGFIX: Use try/finally so temp dir is always cleaned up, even on failure.
        # Previously, if subprocess failed, the temp dir lingered on disk.
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)

        try:
            cmd = [
                self.basisu,
                "-unpack",
                str(ktx2_path),
                "-output_path", str(work_dir),
            ]
            if self.single_threaded:
                cmd.append("-no_multithreading")

            t0 = time.perf_counter()
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir))
            t1 = time.perf_counter()
            if result.returncode != 0:
                raise RuntimeError(
                    f"basisu transcode failed for {ktx2_path}:\n"
                    f"stdout: {result.stdout}\nstderr: {result.stderr}"
                )

            # Find the level-0 ASTC file (highest resolution mipmap).
            # UASTC always transcodes to ASTC 4x4 (the format UASTC is based on).
            astc_candidates = sorted(work_dir.glob("*_ASTC_LDR_4X4_RGBA_level_0_*.astc"))
            if not astc_candidates:
                # Fallback: any ASTC file
                astc_candidates = sorted(work_dir.glob("*.astc"))
            if not astc_candidates:
                raise RuntimeError(f"No .astc output produced for {ktx2_path}")

            # Copy the level-0 ASTC to the final output path
            shutil.copy2(astc_candidates[0], out_path)

            # Sum all ASTC mipmap levels for total size
            total_astc_size = sum(f.stat().st_size for f in work_dir.glob("*.astc"))

            transcode_ms = (t1 - t0) * 1000.0
            return transcode_ms, total_astc_size
        finally:
            # Always clean up the temp dir, even on failure.
            # Don't use ignore_errors=True (silently swallows real errors like
            # permission denied or locked files); log them instead so the user
            # knows orphaned dirs may remain.
            if work_dir.exists():
                import sys
                try:
                    shutil.rmtree(work_dir)
                except OSError as e:
                    print(
                        f"  WARNING: Could not clean up temp dir {work_dir} "
                        f"({type(e).__name__}: {e}). You may need to delete it "
                        f"manually.",
                        file=sys.stderr,
                    )

    def process_texture(self, src_path: Path, out_dir: Path) -> TextureResult:
        """Process a single texture through the full AOT pipeline."""
        src_path = src_path.resolve()
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = src_path.stem
        ktx2_path = out_dir / f"{stem}.ktx2"
        astc_path = out_dir / f"{stem}.astc"

        src_size = src_path.stat().st_size
        src_format = self.detect_source_format(src_path)

        # Compute raw RGBA bytes for proper compression comparison
        raw_rgba_bytes = self._compute_raw_rgba_bytes(src_path)

        # Step 1: Encode to KTX2/UASTC (AOT, slow)
        encode_ms, ktx2_size = self.encode_to_ktx2_uastc(src_path, ktx2_path)

        # Step 2: Transcode to ASTC (on-device, fast)
        transcode_ms, astc_size = self.transcode_to_astc(ktx2_path, astc_path)

        # Sanity check: warn if compression made the file LARGER than raw RGBA.
        # This happens with noisy/high-entropy textures (random noise, dense
        # detail maps) where UASTC can't find redundancy to exploit. In that
        # case, the user may want to:
        #   - Use the ETC1S codec (lower quality but always compresses)
        #   - Use a lower UASTC quality level
        #   - Skip this texture and use raw ASTC directly
        if ktx2_size > raw_rgba_bytes:
            import sys
            print(
                f"  WARNING: KTX2 output ({ktx2_size:,} bytes) is larger than "
                f"raw RGBA ({raw_rgba_bytes:,} bytes) for {src_path.name}. "
                f"Consider using ETC1S codec or lowering UASTC quality.",
                file=sys.stderr,
            )

        result = TextureResult(
            source_file=str(src_path),
            source_format=src_format,
            source_size_bytes=src_size,
            raw_rgba_bytes=raw_rgba_bytes,
            ktx2_file=str(ktx2_path),
            ktx2_size_bytes=ktx2_size,
            ktx2_encode_time_ms=encode_ms,
            astc_file=str(astc_path),
            astc_size_bytes=astc_size,
            astc_transcode_time_ms=transcode_ms,
            compression_ratio=raw_rgba_bytes / max(ktx2_size, 1),
            transcode_overhead=astc_size / max(ktx2_size, 1),
        )
        return result

    def _compute_raw_rgba_bytes(self, src_path: Path) -> int:
        """Compute raw RGBA byte count (W*H*4) for proper compression comparison.

        For PNG/JPG/etc., we use Pillow to read image dimensions.
        For DDS/EXR/HDR, Pillow can't parse them - we'd need dedicated parsers
        (tinydds, tinyexr). Until we add those, we raise an explicit error
        rather than return a wrong estimate that would corrupt compression stats.

        Prior behavior: silently returned filesize*32 for DDS or filesize*4
        for other unknown formats. These multipliers are wildly wrong:
          - DDS BCn files are 0.5-1 bpp, raw RGBA is 32 bpp, so a multiplier
            of 32 overestimates 32-64x.
          - PNG is already compressed, so filesize*4 is meaningless.
        Wrong raw_rgba_bytes makes compression_ratio misleading and hides
        regressions. Better to fail loud than report wrong numbers.
        """
        try:
            from PIL import Image
        except ImportError as e:
            raise RuntimeError(
                f"Pillow is required to compute raw RGBA byte count for "
                f"{src_path.name}. Install with: pip3 install Pillow\n"
                f"Underlying error: {e}"
            ) from e

        try:
            with Image.open(src_path) as img:
                w, h = img.size
                return w * h * 4  # 4 bytes per pixel (RGBA8)
        except Exception as e:
            # Pillow can't open this file (DDS, EXR, HDR, or corrupted image).
            # For Phase 1 PoC, we only test with PNG so this shouldn't happen.
            # When we add real DDS/EXR support, we'll add tinydds/tinyexr here.
            raise RuntimeError(
                f"Could not read image dimensions for {src_path} via Pillow "
                f"({type(e).__name__}: {e}). If this is a .dds/.exr/.hdr file, "
                f"we need to add a dedicated parser (tinydds/tinyexr)."
            ) from e

    def process_directory(
        self, src_dir: Path, out_dir: Path
    ) -> list[TextureResult]:
        """Process all supported textures in a directory."""
        supported = {".png", ".jpg", ".jpeg", ".tga", ".qoi", ".dds", ".exr", ".hdr"}
        results = []
        for src_path in sorted(src_dir.iterdir()):
            if src_path.is_file() and src_path.suffix.lower() in supported:
                print(f"  Processing: {src_path.name} ...", end=" ", flush=True)
                try:
                    r = self.process_texture(src_path, out_dir)
                    print(
                        f"OK  src={r.source_size_bytes}B  "
                        f"ktx2={r.ktx2_size_bytes}B ({r.ktx2_encode_time_ms:.0f}ms)  "
                        f"astc={r.astc_size_bytes}B ({r.astc_transcode_time_ms:.0f}ms)  "
                        f"ratio={r.compression_ratio:.2f}x"
                    )
                    results.append(r)
                except Exception as e:
                    print(f"FAIL: {e}")
        return results


# =============================================================================
# Synthetic test texture generation (for PoC - real use reads .dds files)
# =============================================================================

def generate_test_textures(out_dir: Path) -> list[Path]:
    """Generate synthetic test textures that mimic typical PC game texture types."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("Pillow is required: pip3 install Pillow")

    out_dir.mkdir(parents=True, exist_ok=True)
    textures = []

    # Texture 1: Solid color with noise - mimics UI/atlas textures
    # PC games often use 1024x1024 BC7 for UI atlases.
    img = Image.new("RGBA", (1024, 1024), (128, 64, 200, 255))
    draw = ImageDraw.Draw(img)
    import random
    random.seed(42)
    for _ in range(5000):
        x, y = random.randint(0, 1023), random.randint(0, 1023)
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        draw.point((x, y), (r, g, b, 255))
    p = out_dir / "test_ui_atlas.png"
    img.save(p)
    textures.append(p)

    # Texture 2: Gradient - mimics skybox / smooth surfaces
    img = Image.new("RGBA", (1024, 1024))
    for y in range(1024):
        for x in range(1024):
            r = int(255 * x / 1024)
            g = int(255 * y / 1024)
            b = int(255 * (1 - (x + y) / 2048))
            img.putpixel((x, y), (r, g, b, 255))
    p = out_dir / "test_gradient_skybox.png"
    img.save(p)
    textures.append(p)

    # Texture 3: Random noise - mimics detail/normal maps (worst case for compression)
    img = Image.new("RGBA", (512, 512))
    random.seed(123)
    for y in range(512):
        for x in range(512):
            v = random.randint(0, 255)
            img.putpixel((x, y), (v, v, v, 255))
    p = out_dir / "test_noise_normalmap.png"
    img.save(p)
    textures.append(p)

    return textures


# =============================================================================
# CLI entry point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Aurora Emulator - AOT Texture Transcoder (Phase 1 PoC)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Subcommand: process a directory of textures
    p_proc = sub.add_parser("process", help="Process textures in a directory")
    p_proc.add_argument("input_dir", type=Path)
    p_proc.add_argument("output_dir", type=Path)
    p_proc.add_argument("--quality", choices=["fast", "default", "max"], default="default")

    # Subcommand: run the built-in PoC test
    # Default test paths are relative to the project root (parent of src/)
    _project_root = Path(__file__).resolve().parents[2]
    p_test = sub.add_parser("test", help="Run built-in PoC with synthetic textures")
    p_test.add_argument(
        "--output_dir",
        type=Path,
        default=_project_root / "tests" / "texture_engine_output",
    )
    p_test.add_argument("--quality", choices=["fast", "default", "max"], default="default")

    args = parser.parse_args()

    if args.cmd == "process":
        transcoder = AOTTextureTranscoder(quality=args.quality)
        results = transcoder.process_directory(args.input_dir, args.output_dir)
        meta_path = args.output_dir / "pipeline_results.json"
        meta_path.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nWrote pipeline results: {meta_path}")
        print(f"Processed {len(results)} textures.")

    elif args.cmd == "test":
        test_src_dir = _project_root / "tests" / "texture_engine_input"
        print("=== Aurora Emulator - Phase 1 PoC: AOT Texture Transcoder ===\n")
        print(f"[1/3] Generating synthetic test textures in {test_src_dir} ...")
        textures = generate_test_textures(test_src_dir)
        for t in textures:
            print(f"      - {t.name}  ({t.stat().st_size:,} bytes)")

        print(f"\n[2/3] Running AOT pipeline (quality={args.quality}) ...")
        transcoder = AOTTextureTranscoder(quality=args.quality)
        results = transcoder.process_directory(test_src_dir, args.output_dir)

        print(f"\n[3/3] Summary:")
        if results:
            total_src = sum(r.source_size_bytes for r in results)
            total_raw = sum(r.raw_rgba_bytes for r in results)
            total_ktx2 = sum(r.ktx2_size_bytes for r in results)
            total_astc = sum(r.astc_size_bytes for r in results)
            total_encode = sum(r.ktx2_encode_time_ms for r in results)
            total_transcode = sum(r.astc_transcode_time_ms for r in results)
            print(f"  Source (PNG/etc):  {total_src:>12,} bytes (already-compressed input)")
            print(f"  Raw RGBA:          {total_raw:>12,} bytes (uncompressed, what games upload)")
            print(f"  KTX2/UASTC:        {total_ktx2:>12,} bytes  "
                  f"(AOT encode: {total_encode:.0f}ms)")
            print(f"  ASTC 4x4:          {total_astc:>12,} bytes  "
                  f"(transcode: {total_transcode:.0f}ms)")
            print()
            print(f"  Compression vs raw:  {total_raw/max(total_ktx2,1):.2f}x  "
                  f"(raw RGBA -> KTX2/UASTC, what we ship)")
            print(f"  Transcode overhead:  {total_astc/max(total_ktx2,1):.2f}x  "
                  f"(KTX2 -> ASTC at load time, expected ~1.5-3x due to no zstd)")
            print()
            print(f"  NOTE: On a real device, transcode is a library call to")
            print(f"  basisu_transcoder.cpp (single-file, no deps), running in")
            print(f"  microseconds per block — NOT a subprocess. The {total_transcode:.0f}ms")
            print(f"  measured here includes process spawn + ALL formats (BC1/BC3/BC7/")
            print(f"  ETC1/ETC2/PVRTC/ASTC) — production would only produce ASTC.")

        meta_path = args.output_dir / "pipeline_results.json"
        meta_path.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nResults JSON: {meta_path}")
        print(f"KTX2/ASTC outputs: {args.output_dir}/")


if __name__ == "__main__":
    main()
