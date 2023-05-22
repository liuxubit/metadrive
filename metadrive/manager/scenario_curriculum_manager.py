from collections import deque, OrderedDict

from metadrive.manager.base_manager import BaseManager
from metadrive.manager.scenario_data_manager import ScenarioDataManager


class QueueDict:
    def __init__(self, max_length):
        self.queue = deque(maxlen=max_length)
        self.dict = OrderedDict()

    def put(self, key, value):
        # Remove the key from the queue if it already exists
        if key in self.dict:
            self.queue.remove(key)
        # Else, ensure we don't exceed the max length
        elif len(self.queue) == self.queue.maxlen:
            oldest_key = self.queue.popleft()
            del self.dict[oldest_key]

        # Add the key to the queue, and update the dictionary
        self.queue.append(key)
        self.dict[key] = value

    def get(self, key):
        if key in self.dict:
            return self.dict[key]
        else:
            return None

    def items(self):
        return self.dict.items()

    def __len__(self):
        return len(self.dict)


class ScenarioCurriculumManager(BaseManager):
    PRIORITY = ScenarioDataManager.PRIORITY - 1

    def __init__(self):
        super().__init__()
        self._episodes_to_eval = self.engine.global_config["episodes_to_evaluate_curriculum"]
        self.recent_route_completion = QueueDict(max_length=self._episodes_to_eval)
        self.recent_success = QueueDict(max_length=self._episodes_to_eval)
        self.target_success_rate = self.engine.global_config["target_success_rate"]
        # assert self.engine.global_config["start_scenario_index"] ==0, "For curriculum training, start_index should be 0"

    def log_episode(self, success, route_completion):
        self.recent_route_completion.put(self.engine.data_manager.current_scenario_id, route_completion)
        self.recent_success.put(self.engine.data_manager.current_scenario_id, success)

    def before_reset(self):
        """
        It should be called before reseting all managers
        """
        if sum(self.recent_success.dict.values()) / self._episodes_to_eval > self.target_success_rate \
                and self.engine.current_level < self.engine.max_level - 1:
            self.engine.level_up()
            self.recent_route_completion = QueueDict(max_length=self._episodes_to_eval)
            self.recent_success = QueueDict(max_length=self._episodes_to_eval)
            self.engine.map_manager.clear_stored_maps()
            self.engine.data_manager.clear_stored_scenarios()
