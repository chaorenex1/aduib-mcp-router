import asyncio
import threading
from concurrent import futures

async_thread_pool = futures.ThreadPoolExecutor(thread_name_prefix='async_thread_pool')

class AsyncUtils:
    @classmethod
    def run_async(cls, coro):
        """
            使用线程池在独立事件循环中运行协程任务，
            主线程阻塞等待结果。
            """

        def run_in_thread(coro):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        # 在线程池中执行协程
        future = async_thread_pool.submit(run_in_thread, coro)
        return future.result()




class CountDownLatch:
    """A synchronization aid that allows one or more threads to wait until
    a set of operations being performed in other threads completes.
    """
    def __init__(self, count: int):
        self.count = count
        self.condition = threading.Condition()

    def count_down(self):
        with self.condition:
            self.count -= 1
            if self.count <= 0:
                self.condition.notify_all()

    def await_(self):
        with self.condition:
            while self.count > 0:
                self.condition.wait()
