"""
使用雪花算法生成唯一ID
"""
import logging
import time

from aduib_app import AduibAIApp
from configs import config

log=logging.getLogger(__name__)

class SnowflakeIDGenerator:
    def __init__(self):
        self.last_timestamp = None
        self.sequence = None
        self.machine_id_left_shift = None
        self.datacenter_id_left_shift = None
        self.timestamp_left_shift = None
        self.max_sequence = None
        self.max_datacenter_id = None
        self.max_machine_id = None
        self.sequence_bits = None
        self.datacenter_id_bits = None
        self.machine_id_bits = None
        self.epoch = None
        self.datacenter_id = None
        self.machine_id = None

    def init(self, machine_id=1, datacenter_id=1, epoch=1739671820000):
        """
        :param machine_id: 机器 ID (0 - 1023)
        :param datacenter_id: 数据中心 ID (0 - 31)
        :param epoch: 自定义纪元时间，默认是 2021年1月1日的时间戳
        """
        self.machine_id = machine_id
        self.datacenter_id = datacenter_id
        self.epoch = epoch

        # 位移配置
        self.machine_id_bits = 10
        self.datacenter_id_bits = 5
        self.sequence_bits = 12

        # 最大值
        self.max_machine_id = (1 << self.machine_id_bits) - 1  # 1023
        self.max_datacenter_id = (1 << self.datacenter_id_bits) - 1  # 31
        self.max_sequence = (1 << self.sequence_bits) - 1  # 4095

        # 位移量
        self.timestamp_left_shift = self.sequence_bits + self.datacenter_id_bits + self.machine_id_bits
        self.datacenter_id_left_shift = self.sequence_bits + self.machine_id_bits
        self.machine_id_left_shift = self.sequence_bits

        self.sequence = 0
        self.last_timestamp = -1

        # 检查机器ID和数据中心ID的有效性
        if not (0 <= machine_id <= self.max_machine_id):
            raise ValueError(f"machine_id must be between 0 and {self.max_machine_id}")
        if not (0 <= datacenter_id <= self.max_datacenter_id):
            raise ValueError(f"datacenter_id must be between 0 and {self.max_datacenter_id}")

    def _current_timestamp(self):
        return int(time.time() * 1000) - self.epoch  # 当前时间戳减去纪元时间戳

    def _wait_for_next_millis(self, last_timestamp):
        timestamp = self._current_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._current_timestamp()
        return timestamp

    def generate(self)->int:
        timestamp = self._current_timestamp()

        # 如果时间戳没有变化，使用序列号递增
        if timestamp == self.last_timestamp:
            self.sequence = (self.sequence + 1) & self.max_sequence
            if self.sequence == 0:
                timestamp = self._wait_for_next_millis(self.last_timestamp)
        else:
            self.sequence = 0

        self.last_timestamp = timestamp

        # 构建 ID
        snowflake_id = ((timestamp << self.timestamp_left_shift) |
                        (self.datacenter_id << self.datacenter_id_left_shift) |
                        (self.machine_id << self.machine_id_left_shift) |
                        self.sequence)
        return snowflake_id

    def init(self, machine_id, datacenter_id):
        pass


id_generator = SnowflakeIDGenerator()

def init_idGenerator(app:AduibAIApp):
    id_generator.init(config.SNOWFLAKE_WORKER_ID, config.SNOWFLAKE_DATACENTER_ID)
    app.extensions["id_generator"] = id_generator
    log.info(
        f"Snowflake IDGenerator initialized with machine_id={config.SNOWFLAKE_WORKER_ID}, datacenter_id={config.SNOWFLAKE_DATACENTER_ID}")


