from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from rdc_tool import server_runtime


def compare(tmp_path: Path, a: np.ndarray, b: np.ndarray, metrics=None) -> dict:
    left, right = tmp_path / 'left.png', tmp_path / 'right.png'
    Image.fromarray(a).save(left)
    Image.fromarray(b).save(right)
    args = {'image_a_path': str(left), 'image_b_path': str(right),
            'output_path': str(tmp_path / 'diff.png')}
    if metrics is not None:
        args['metrics'] = metrics
    return json.loads(asyncio.run(server_runtime._dispatch_util('diff_images', args)))


def test_diff_is_visible_for_opaque_inputs_and_alpha_only_changes(tmp_path: Path) -> None:
    a = np.zeros((16, 16, 4), dtype=np.uint8)
    a[:, :, 3] = 255
    b = a.copy()
    b[7, 8, 0] = 255
    result = compare(tmp_path, a, b)
    assert result['success'] is True
    assert result['metrics']['mse'] == 1 / (16 * 16 * 4)
    with Image.open(tmp_path / 'diff.png') as image:
        assert image.mode == 'RGB'
        assert image.getpixel((8, 7)) == (255, 0, 0)
        assert image.getpixel((0, 0)) == (0, 0, 0)
    b = a.copy()
    b[7, 8, 3] = 0
    assert compare(tmp_path, a, b)['metrics']['identical'] is False
    with Image.open(tmp_path / 'diff.png') as image:
        assert image.getpixel((8, 7)) == (255, 255, 255)


def test_identical_psnr_is_json_safe_and_small_default_inputs_work(tmp_path: Path) -> None:
    a = np.full((2, 3, 4), 123, dtype=np.uint8)
    result = compare(tmp_path, a, a)
    assert result['success'] is True
    assert result['metrics']['identical'] is True
    assert result['metrics']['mse'] == 0
    assert result['metrics']['psnr'] is None
    assert result['metrics']['psnr_status'] == 'infinite'


def test_ssim_matches_independent_full_kernel_reference(tmp_path: Path) -> None:
    rng = np.random.default_rng(29)
    a = rng.integers(0, 256, (16, 17, 4), dtype=np.uint8)
    b = a.copy()
    b[4:12, 3:14, :3] = b[4:12, 3:14, :3] // 2
    result = compare(tmp_path, a, b, ['ssim'])
    assert result['success'] is True
    metrics = result['metrics']
    assert 'mse' not in metrics and 'psnr' not in metrics
    # Independent two-dimensional window oracle, not the separable production filter.
    axis = np.arange(-5, 6, dtype=np.float64)
    kernel = np.exp(-(axis[:, None] ** 2 + axis[None, :] ** 2) / (2 * 1.5 ** 2))
    kernel /= kernel.sum()
    x, y = (v.astype(np.float32) / 255.0 for v in (a, b))
    scores = []
    for channel in range(4):
        for row in range(a.shape[0] - 10):
            for column in range(a.shape[1] - 10):
                vx = x[row:row + 11, column:column + 11, channel].astype(np.float64)
                vy = y[row:row + 11, column:column + 11, channel].astype(np.float64)
                mx, my = np.sum(kernel * vx), np.sum(kernel * vy)
                sx = np.sum(kernel * (vx - mx) ** 2)
                sy = np.sum(kernel * (vy - my) ** 2)
                cov = np.sum(kernel * (vx - mx) * (vy - my))
                scores.append(((2 * mx * my + 0.01 ** 2) * (2 * cov + 0.03 ** 2))
                              / ((mx * mx + my * my + 0.01 ** 2) * (sx + sy + 0.03 ** 2)))
    assert metrics['ssim'] == pytest.approx(float(np.mean(scores)), abs=1e-11)
    assert metrics['ssim_method'] == {'channels': 'RGBA', 'window': 11, 'sigma': 1.5,
                                      'data_range': 1, 'covariance': 'population', 'boundary': 'valid'}
    assert 0 < metrics['ssim'] < 1
    assert compare(tmp_path, a, a, ['ssim'])['metrics']['ssim'] == pytest.approx(1)


def test_ssim_constant_images_have_known_score(tmp_path: Path) -> None:
    a = np.zeros((11, 11, 4), dtype=np.uint8)
    b = np.full_like(a, 255)
    result = compare(tmp_path, a, b, ['mse', 'max_abs', 'psnr', 'ssim'])
    assert result['metrics']['ssim'] == pytest.approx(0.01 ** 2 / (1 + 0.01 ** 2))
    assert result['metrics']['mse'] == 1
    assert result['metrics']['max_abs'] == 1
    assert result['metrics']['psnr'] == 0


@pytest.mark.parametrize('metrics', [[], ['unknown'], 'psnr', [True]])
def test_invalid_metrics_fail_before_file_access(tmp_path: Path, metrics) -> None:
    result = json.loads(asyncio.run(server_runtime._dispatch_util('diff_images', {
        'image_a_path': str(tmp_path / 'missing-a.png'),
        'image_b_path': str(tmp_path / 'missing-b.png'), 'metrics': metrics,
        'output_path': str(tmp_path / 'diff.png'),
    })))
    assert result['success'] is False and result['code'] == 'validation_error'
    assert not (tmp_path / 'diff.png').exists()


def test_ssim_small_input_and_mismatched_shapes_do_not_write(tmp_path: Path) -> None:
    a = np.zeros((10, 16, 4), dtype=np.uint8)
    result = compare(tmp_path, a, a, ['ssim'])
    assert result['success'] is False and result['code'] == 'ssim_window_too_large'
    assert not (tmp_path / 'diff.png').exists()
    result = compare(tmp_path, a, np.zeros((11, 16, 4), dtype=np.uint8))
    assert result['success'] is False and result['code'] == 'image_shape_mismatch'
    assert not (tmp_path / 'diff.png').exists()


def test_region_separates_target_from_unchanged_control_without_resizing(tmp_path: Path) -> None:
    a = np.zeros((16, 16, 4), dtype=np.uint8)
    a[:, :, 3] = 255
    b = a.copy()
    b[1, 1, 0] = 255
    compare(tmp_path, a, b)
    args = {'image_a_path': str(tmp_path / 'left.png'), 'image_b_path': str(tmp_path / 'right.png'),
            'metrics': ['mse', 'max_abs'], 'output_path': str(tmp_path / 'region.png'),
            'region': {'x': 0, 'y': 0, 'width': 4, 'height': 4}}
    target = json.loads(asyncio.run(server_runtime._dispatch_util('diff_images', args)))['metrics']
    assert target['mse'] == 1 / (4 * 4 * 4) and target['max_abs'] == 1
    assert target['region'] == args['region']
    assert target['source_size'] == {'width': 16, 'height': 16}
    with Image.open(tmp_path / 'region.png') as image:
        assert image.size == (4, 4) and image.mode == 'RGB'
    args['region'] = {'x': 8, 'y': 8, 'width': 8, 'height': 8}
    control = json.loads(asyncio.run(server_runtime._dispatch_util('diff_images', args)))['metrics']
    assert control['identical'] is True and control['mse'] == control['max_abs'] == 0
    with Image.open(tmp_path / 'region.png') as image:
        assert image.size == (8, 8)


@pytest.mark.parametrize('region', [
    {'x': -1, 'y': 0, 'width': 4, 'height': 4},
    {'x': 0, 'y': 0, 'width': 0, 'height': 4},
    {'x': 12, 'y': 0, 'width': 5, 'height': 4},
    {'x': True, 'y': 0, 'width': 4, 'height': 4},
    {'x': 0, 'y': 0, 'width': 4, 'height': 4, 'extra': 1},
])
def test_invalid_region_does_not_write_or_silently_clamp(tmp_path: Path, region) -> None:
    a = np.zeros((16, 16, 4), dtype=np.uint8)
    Image.fromarray(a).save(tmp_path / 'input.png')
    result = json.loads(asyncio.run(server_runtime._dispatch_util('diff_images', {
        'image_a_path': str(tmp_path / 'input.png'), 'image_b_path': str(tmp_path / 'input.png'),
        'region': region, 'output_path': str(tmp_path / 'invalid.png'),
    })))
    assert result['success'] is False and result['code'] == 'invalid_image_region'
    assert not (tmp_path / 'invalid.png').exists()
