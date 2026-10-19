"""Emergency compute CLI and media goal entrypoints, sharing the API transport."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import uuid
from pathlib import Path

from services.core.cli_files import write_output

from .client import ComputeClient, ComputeError
from .runners import VisionRunner, VoiceRunner, device_session, selected_executor


def run_goal(domain: str, cfg: dict | None = None, *, once: bool = False, selection=None) -> int:
    selected = selection or selected_executor()
    if selected is None:
        raise ComputeError('compute_executor_not_selected')
    from common.bus import BusPub

    publisher = BusPub()
    runner = None
    previous = {}
    try:
        runner = (
            VoiceRunner(selected, cfg or {}, publisher=publisher)
            if domain == 'voice'
            else VisionRunner(
                selected,
                publisher=publisher,
            )
        )
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            # A signal can interrupt HTTP while its non-reentrant lock is held.
            # Leave cancellation/handle closure to the runner's finally path.
            signal.signal(signum, lambda *_: runner.stop_event.set())
        return runner.run(once=once)
    finally:
        if runner is not None:
            runner.close()
        else:
            publisher.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capabilities', 'text', 'tts', 'vision', 'voice'))
    parser.add_argument('--text')
    parser.add_argument('--output', type=Path, help='WAV path for tts; does not start playback')
    parser.add_argument('--language', choices=('pl', 'en', 'de'), default='pl')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    try:
        selection = selected_executor()
        if selection is None:
            raise ComputeError('compute_executor_not_selected')
        if args.action in {'voice', 'vision'}:
            from apps.voice.config import load

            return run_goal(
                args.action, load() if args.action == 'voice' else None, once=args.once, selection=selection
            )
        with ComputeClient(
            selection['url'],
            selection['device_id'],
            selection.get('token', ''),
            device_session(),
            selection['id'],
            client_id='cli',
        ) as client:
            if args.action == 'capabilities':
                result = client.capabilities()
            else:
                task = 'text.respond' if args.action == 'text' else 'audio.synthesize'
                if task not in selection.get('tasks', []):
                    raise ComputeError('compute_task_not_selected')
                text = args.text if args.text is not None else sys.stdin.read(4097)
                job_id = client.submit(
                    task,
                    text.encode('utf-8'),
                    'text/plain; charset=utf-8',
                    {
                        'captured_at': time.time(),
                        'input_id': uuid.uuid4().hex,
                        'stream_id': 'cli',
                        'sequence': 1,
                        'ttl_ms': 60000,
                        'timestamp_source': 'operator_input',
                    },
                    params={'language': args.language},
                )
                result = client.result(job_id, timeout=60)
                if args.action == 'tts':
                    if args.output is None:
                        raise ComputeError('compute_output_path_required')
                    output = client.output(job_id)
                    write_output(args.output, output)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ComputeError, ValueError, OSError) as exc:
        code = exc.code if isinstance(exc, ComputeError) else 'compute_configuration_or_io_error'
        print(json.dumps({'ok': False, 'error': code}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
