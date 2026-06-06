import asyncio
from typing import Dict, Optional

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, asyncio.Task] = {}

    def add_task(self, task_id: str, task: asyncio.Task):
        self.tasks[task_id] = task

    def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            del self.tasks[task_id]
            return True
        return False

    def remove_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]

task_manager = TaskManager()
