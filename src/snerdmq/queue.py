import asyncio
import json
import os
import signal
import sys
from typing import Callable, Awaitable, Dict, Any, Optional

class SnerdQueue:
    def __init__(self, binary_path: Optional[str] = None, storage_path: Optional[str] = None):
        self.handlers: Dict[str, Callable[[Any], Awaitable[None]]] = {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.is_shutting_down = False
        
        if not binary_path:
            package_dir = os.path.dirname(os.path.abspath(__file__))
            ext = '.exe' if os.name == 'nt' else ''
            binary_path = os.path.join(package_dir, 'bin', f'snerdmq{ext}')

        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"[Snerd] Binary not found at {binary_path}. Please run 'snerdmq-install' or provide binary_path.")

        self.binary_path = binary_path
        self.storage_path = storage_path

        # Handle graceful shutdown signals
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, self.shutdown)
            except NotImplementedError:
                pass # Windows does not support add_signal_handler easily

    async def start_listening(self):
        """Starts the rust daemon and the event loop to listen to its output."""
        args = [self.storage_path] if self.storage_path else []
        self.process = await asyncio.create_subprocess_exec(
            self.binary_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        if not self.process.stdout or not self.process.stderr:
            raise RuntimeError("[Snerd] Failed to establish standard I/O pipes.")

        # Re-send all registrations in case we are reconnecting
        for task_type in self.handlers.keys():
            await self._send({"action": "register", "task_type": task_type})

        # Run stdout and stderr readers concurrently
        await asyncio.gather(
            self._read_stdout(),
            self._read_stderr()
        )

    async def _read_stdout(self):
        assert self.process and self.process.stdout
        while not self.is_shutting_down:
            line = await self.process.stdout.readline()
            if not line:
                break
            line_str = line.decode().strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
                # Dispatch handler without blocking the read loop
                asyncio.create_task(self._handle_engine_message(msg))
            except json.JSONDecodeError:
                pass

        if not self.is_shutting_down:
            print("[Snerd] Engine process terminated unexpectedly.", file=sys.stderr)

    async def _read_stderr(self):
        assert self.process and self.process.stderr
        while not self.is_shutting_down:
            line = await self.process.stderr.readline()
            if not line:
                break
            print(f"[Snerd Engine Error]: {line.decode().strip()}", file=sys.stderr)

    async def _handle_engine_message(self, msg: dict):
        if msg.get('action') == 'execute':
            task_type = msg.get('task_type')
            task_id = msg.get('task_id')
            task_data = msg.get('task_data')
            
            if isinstance(task_data, str):
                try:
                    task_data = json.loads(task_data)
                except json.JSONDecodeError:
                    pass

            handler = self.handlers.get(task_type)
            if not handler:
                await self._send({'action': 'result', 'task_id': task_id, 'status': 'error', 'error_msg': 'No handler registered.'})
                return

            try:
                await handler(task_data)
                await self._send({'action': 'result', 'task_id': task_id, 'status': 'success'})
            except Exception as e:
                await self._send({'action': 'result', 'task_id': task_id, 'status': 'error', 'error_msg': str(e)})

        elif msg.get('action') == 'max_retries_reached':
            print(f"[Snerd] Dead Letter Queue: Task {msg.get('task_id')} ({msg.get('task_type')}) permanently failed.", file=sys.stderr)

    async def _send(self, msg: dict):
        if self.process and self.process.stdin and not self.is_shutting_down:
            self.process.stdin.write((json.dumps(msg) + '\n').encode())
            await self.process.stdin.drain()

    def register_handler(self, task_type: str, handler: Callable[[Any], Awaitable[None]]):
        """Registers an async function to handle a specific task type."""
        self.handlers[task_type] = handler
        if self.process:
            asyncio.create_task(self._send({"action": "register", "task_type": task_type}))

    async def enqueue(self, task_id: str, task_type: str, data: Any, max_retries: int = 3, retry_after_hours: float = 0.0):
        """Enqueues a new background job."""
        if not self.process:
            raise RuntimeError("[Snerd] Cannot enqueue task: Queue is not running. Call start_listening() first.")
        
        await self._send({
            'action': 'enqueue',
            'task_id': task_id,
            'task_type': task_type,
            'task_data': json.dumps(data),
            'max_retries': max_retries,
            'retry_after_hours': retry_after_hours
        })

    def shutdown(self):
        """Gracefully kills the Rust daemon."""
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        if self.process:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
