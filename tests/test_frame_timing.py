import asyncio
from types import SimpleNamespace as NS

import pytest

from rdc_tool.core.perf_service import measure_frame_gpu


def fixture_controller(values):
    iterator = iter(values)
    def fetch(counters):
        assert counters == [17]
        return [NS(counter=17, eventId=0, value=NS(d=next(iterator)))]
    return NS(EnumerateCounters=lambda: [17],
              DescribeCounter=lambda _: NS(unit=1, resultType=1, resultByteWidth=8),
              GetRootActions=lambda: [NS(eventId=14, children=[])], FetchCounters=fetch)


def test_frame_samples_preserve_native_seconds_and_discard_only_warmup():
    result = asyncio.run(measure_frame_gpu(fixture_controller([0.03, 0.002, 0.004]),
                         NS(GPUCounter=NS(FrameGPUDuration=17)), samples=2, warmup=1))
    assert result['samples'] == [0.002, 0.004]
    assert result['range'] == {'first_event_id': 1, 'last_event_id': 14}
    assert result['unit'] == 'seconds' and result['sampling'] == {'samples': 2, 'warmup': 1}
    assert result['includes_initial_contents'] is False
    assert result['original_application_frame_time'] is False


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_invalid_native_timestamp_is_not_a_sample(value):
    with pytest.raises(ValueError):
        asyncio.run(measure_frame_gpu(fixture_controller([value]),
                    NS(GPUCounter=NS(FrameGPUDuration=17)), samples=1, warmup=0))


def test_unavailable_and_incomplete_queue_measurement_fail():
    rd = NS(GPUCounter=NS(FrameGPUDuration=17))
    controller = fixture_controller([0.1])
    controller.EnumerateCounters = lambda: [1]
    with pytest.raises(RuntimeError, match='queue configuration'):
        asyncio.run(measure_frame_gpu(controller, rd, samples=1, warmup=0))
    controller.EnumerateCounters = lambda: [17]
    controller.FetchCounters = lambda _: []
    with pytest.raises(RuntimeError, match='incomplete sample'):
        asyncio.run(measure_frame_gpu(controller, rd, samples=1, warmup=0))
