#!/usr/bin/env python3
"""
Unit tests for scripts/config-init.sh script
"""

import os
import subprocess
import tempfile
from pathlib import Path


def test_config_init_creates_missing_files(tmp_path):
    """Test that config-init.sh creates .toml files from .toml.example templates."""
    # Create a temporary config directory
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create some .toml.example files
    (config_dir / "test1.toml.example").write_text("[test]\nkey1 = 'value1'\n")
    (config_dir / "test2.toml.example").write_text("[test]\nkey2 = 'value2'\n")

    # Create a mock scripts directory
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Copy the config-init.sh script to the temp directory
    repo_root = Path(__file__).parent.parent
    original_script = repo_root / "scripts" / "config-init.sh"

    # Create a modified version that uses our temp paths
    script_content = original_script.read_text()
    script_content = script_content.replace('CONFIG_DIR="${REPO_ROOT}/config"', f'CONFIG_DIR="{config_dir}"')

    test_script = scripts_dir / "config-init.sh"
    test_script.write_text(script_content)
    test_script.chmod(0o755)

    # Run the script
    result = subprocess.run(
        [str(test_script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )

    # Check exit code
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Check that .toml files were created
    assert (config_dir / "test1.toml").exists()
    assert (config_dir / "test2.toml").exists()

    # Verify content
    assert (config_dir / "test1.toml").read_text() == "[test]\nkey1 = 'value1'\n"
    assert (config_dir / "test2.toml").read_text() == "[test]\nkey2 = 'value2'\n"

    # Check output messages
    assert "Created test1.toml" in result.stdout
    assert "Created test2.toml" in result.stdout
    assert "Files created: 2" in result.stdout


def test_config_init_skips_existing_files(tmp_path):
    """Test that config-init.sh does not overwrite existing .toml files."""
    # Create a temporary config directory
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create a .toml.example file
    (config_dir / "test.toml.example").write_text("[test]\nkey = 'template'\n")

    # Create an existing .toml file with different content
    existing_content = "[test]\nkey = 'existing'\n"
    (config_dir / "test.toml").write_text(existing_content)

    # Create a mock scripts directory
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Copy and modify the script
    repo_root = Path(__file__).parent.parent
    original_script = repo_root / "scripts" / "config-init.sh"
    script_content = original_script.read_text()
    script_content = script_content.replace('CONFIG_DIR="${REPO_ROOT}/config"', f'CONFIG_DIR="{config_dir}"')

    test_script = scripts_dir / "config-init.sh"
    test_script.write_text(script_content)
    test_script.chmod(0o755)

    # Run the script
    result = subprocess.run(
        [str(test_script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )

    # Check exit code
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Verify the existing file was NOT overwritten
    assert (config_dir / "test.toml").read_text() == existing_content

    # Check output messages
    assert "already exists, skipping" in result.stdout
    assert "Files created: 0" in result.stdout
    assert "Files skipped" in result.stdout and "1" in result.stdout


def test_config_init_handles_empty_directory(tmp_path):
    """Test that config-init.sh handles an empty config directory gracefully."""
    # Create an empty config directory
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create a mock scripts directory
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Copy and modify the script
    repo_root = Path(__file__).parent.parent
    original_script = repo_root / "scripts" / "config-init.sh"
    script_content = original_script.read_text()
    script_content = script_content.replace('CONFIG_DIR="${REPO_ROOT}/config"', f'CONFIG_DIR="{config_dir}"')

    test_script = scripts_dir / "config-init.sh"
    test_script.write_text(script_content)
    test_script.chmod(0o755)

    # Run the script
    result = subprocess.run(
        [str(test_script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )

    # Check exit code
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Check output messages
    assert "Total templates found: 0" in result.stdout
    assert "Files created: 0" in result.stdout


def test_config_init_real_templates():
    """Test config-init.sh with actual repository templates."""
    repo_root = Path(__file__).parent.parent
    config_dir = repo_root / "config"

    # Check that our template files exist
    assert (config_dir / "vision.toml.example").exists(), "vision.toml.example should exist"
    assert (config_dir / "voice_web.toml.example").exists(), "voice_web.toml.example should exist"

    # Read template content to verify structure
    vision_content = (config_dir / "vision.toml.example").read_text()
    assert "[paths]" in vision_content
    assert "snap_dir" in vision_content
    assert "[detector]" in vision_content

    voice_web_content = (config_dir / "voice_web.toml.example").read_text()
    assert "[models]" in voice_web_content
    assert "piper_model_dir" in voice_web_content
    assert "vosk_model_dir" in voice_web_content
    assert "[server]" in voice_web_content
