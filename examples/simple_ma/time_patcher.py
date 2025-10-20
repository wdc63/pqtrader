# time_patcher.py

import datetime
import time
import importlib

class TimePatcher:
    """
    通过猴子补丁（Monkey Patching）来控制 `datetime.now()` 的返回值，
    用于测试需要伪造时间、加速时间流逝的场景。

    它通过替换目标模块中的 `datetime` 类来实现，这是一个更安全和可靠的方法。
    """
    def __init__(self, initial_datetime=None, time_speed=1.0, target_module_names=None):
        self._fake_start_time = initial_datetime or datetime.datetime.now()
        self._real_start_time = None
        self._time_speed = time_speed
        # [MODIFIED] 支持对多个模块打补丁
        if target_module_names is None:
            target_module_names = ['qtrader.core.engine']
        self._target_module_names = target_module_names
        self._original_datetimes = {}  # {module_name: original_datetime}
        self._target_modules = {}      # {module_name: module_object}

    def _get_mock_now(self):
        """根据真实流逝的时间和时间倍率，计算并返回伪造的当前时间"""
        if self._real_start_time is None:
            return self._fake_start_time
        real_elapsed_seconds = time.time() - self._real_start_time
        fake_elapsed = datetime.timedelta(seconds=real_elapsed_seconds * self._time_speed)
        return self._fake_start_time + fake_elapsed

    def patch(self):
        """[MODIFIED] 应用补丁，替换掉所有目标模块中的 datetime 类"""
        if self._original_datetimes:
            return  # Already patched

        # 创建一个继承自真实datetime的Mock类。
        # 这个类定义在patch方法内部，以便通过闭包捕acts self (TimePatcher实例)
        class MockDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                # 调用外部 TimePatcher 实例的 _get_mock_now 方法
                return self._get_mock_now()

        for module_name in self._target_module_names:
            try:
                # 动态导入目标模块
                module = importlib.import_module(module_name)
                
                # 检查模块是否真的有 datetime 属性
                if hasattr(module, 'datetime'):
                    self._target_modules[module_name] = module
                    self._original_datetimes[module_name] = module.datetime
                    module.datetime = MockDateTime
                    print(f"[TimePatcher] Patched 'datetime' in module '{module_name}'.")
                else:
                    print(f"[TimePatcher] Warning: Module '{module_name}' has no 'datetime' attribute to patch.")

            except ImportError:
                print(f"[TimePatcher] Warning: Could not import target module '{module_name}' to patch.")

        self._real_start_time = time.time()
        print(f"[TimePatcher] Fake time starts at: {self._fake_start_time}, Speed: {self._time_speed}x")

    def unpatch(self):
        """[MODIFIED] 移除补丁，恢复所有目标模块原始的 datetime 类"""
        if not self._original_datetimes:
            return

        for module_name, original_datetime in self._original_datetimes.items():
            if module_name in self._target_modules:
                try:
                    self._target_modules[module_name].datetime = original_datetime
                    print(f"[TimePatcher] Unpatched 'datetime' in module '{module_name}'.")
                except Exception as e:
                    print(f"[TimePatcher] Error unpatching module '{module_name}': {e}")
        
        self._original_datetimes.clear()
        self._target_modules.clear()
        print("[TimePatcher] All patches removed.")

    def set(self, new_datetime: datetime.datetime):
        """直接设置当前的伪造时间，并以此为新起点继续按倍率流逝"""
        self._fake_start_time = new_datetime
        if self._original_datetimes:  # 如果补丁已生效
            self._real_start_time = time.time()
        print(f"[TimePatcher] Time reset to: {self._fake_start_time}")

    def advance(self, **kwargs):
        """
        按指定的时间增量推进伪造时间, 并以此为新起点继续按倍率流逝
        参数同 `datetime.timedelta` (e.g., days=1, hours=2).
        """
        current_fake_time = self._get_mock_now()
        delta = datetime.timedelta(**kwargs)
        self._fake_start_time = current_fake_time + delta
        if self._original_datetimes:  # 如果补丁已生效
            self._real_start_time = time.time()
        print(f"[TimePatcher] Time advanced by {delta}. New base time: {self._fake_start_time}")

    def __enter__(self):
        self.patch()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unpatch()