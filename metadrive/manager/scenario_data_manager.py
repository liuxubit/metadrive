import copy
import os

import numpy as np

from metadrive.manager.base_manager import BaseManager
from metadrive.scenario.scenario_description import ScenarioDescription as SD, MetaDriveType
from metadrive.scenario.utils import read_scenario_data, read_dataset_summary
from metadrive.utils.data_buffer import DataBuffer


class ScenarioDataManager(BaseManager):
    DEFAULT_DATA_BUFFER_SIZE = 100
    PRIORITY = -10

    def __init__(self):
        super(ScenarioDataManager, self).__init__()
        from metadrive.engine.engine_utils import get_engine
        engine = get_engine()

        self.store_map = engine.global_config.get("store_map", False)
        store_map_buffer_size = engine.global_config.get("store_map_buffer_size", self.DEFAULT_DATA_BUFFER_SIZE)
        self.directory = engine.global_config["data_directory"]
        self.num_scenarios = engine.global_config["num_scenarios"]
        self.start_scenario_index = engine.global_config["start_scenario_index"]

        self._scenario = DataBuffer(store_map_buffer_size if self.store_map else self.num_scenarios)
        self._total_level = self.engine.global_config["curriculum_level"]
        self._current_level = 0
        self.num_scenarios_per_level = int(self.num_scenarios / self._total_level)

        # Read summary file first:
        self.summary_dict, self.summary_lookup, self.mapping = read_dataset_summary(self.directory)

        self.sort_scenarios()

        # existence check
        for p in self.summary_dict.keys():
            p = os.path.join(self.directory, self.mapping[p], p)
            assert os.path.exists(p), "No Data at path: {}".format(p)

    @property
    def current_scenario_summary(self):
        return self.current_scenario[SD.METADATA]

    def _get_scenario(self, i):
        assert self.start_scenario_index <= i < self.start_scenario_index + self.num_scenarios, \
            "scenario ID exceeds range"
        assert i < len(self.summary_lookup)
        scenario_id = self.summary_lookup[i]
        file_path = os.path.join(self.directory, self.mapping[scenario_id], scenario_id)
        ret = read_scenario_data(file_path)
        assert isinstance(ret, SD)
        return ret

    def get_scenario(self, i, should_copy=False):

        _debug_memory_leak = False

        if i not in self._scenario:

            if _debug_memory_leak:
                # inner psutil function
                def process_memory():
                    import psutil
                    import os
                    process = psutil.Process(os.getpid())
                    mem_info = process.memory_info()
                    return mem_info.rss

                cm = process_memory()

            self._scenario.clear_if_necessary()

            if _debug_memory_leak:
                lm = process_memory()
                print("{}:  Reset! Mem Change {:.3f}MB".format("data manager clear scenario", (lm - cm) / 1e6))
                cm = lm

            # print("===Getting new scenario: ", i)
            self._scenario[i] = self._get_scenario(i)

            if _debug_memory_leak:
                lm = process_memory()
                print("{}:  Reset! Mem Change {:.3f}MB".format("data manager read scenario", (lm - cm) / 1e6))
                cm = lm

        else:
            pass
            # print("===Don't need to get new scenario. Just return: ", i)

        if should_copy:
            return copy.deepcopy(self._scenario[i])

        # Data Manager is the first manager that accesses  data.
        # It is proper to let it validate the metadata and change the global config if needed.
        ret = self._scenario[i]

        return ret

    def get_metadata(self):
        state = super(ScenarioDataManager, self).get_metadata()
        raw_data = self.current_scenario
        state["raw_data"] = raw_data
        return state

    def transform_coordinate(self, scenario):
        raise ValueError("Deprecated now as all coordinates is right-handed now")
        if not self.engine.global_config["allow_coordinate_transform"]:
            assert scenario[SD.METADATA][SD.COORDINATE] == MetaDriveType.COORDINATE_METADRIVE, \
                "Only support MetaDrive coordinate!"
        else:
            # It supports loading WaymoData or exported data in two coordinates
            if scenario[SD.METADATA][SD.COORDINATE] == MetaDriveType.COORDINATE_WAYMO:
                self._coordinate_transform = True
            elif scenario[SD.METADATA][SD.COORDINATE] == MetaDriveType.COORDINATE_METADRIVE:
                self._coordinate_transform = False
            else:
                raise ValueError()

    @property
    def current_scenario_length(self):
        return self.current_scenario[SD.LENGTH]

    @property
    def current_scenario(self):
        seed = self.engine.global_random_seed % self.num_scenarios_per_level
        return self.get_scenario(seed + self._current_level * self.num_scenarios_per_level)

    def sort_scenarios(self):
        """
        TODO(LQY): consider exposing this API to config
        Sort scenarios to support curriculum training. You are encouraged to customize your own sort method
        :return: sorted scenario list
        """
        if self._total_level == 1:
            return

        def _score(scenario_id):
            file_path = os.path.join(self.directory, self.mapping[scenario_id], scenario_id)
            scenario = read_scenario_data(file_path)
            obj_weight = 0

            # calculate curvature
            ego_car_id = scenario[SD.METADATA][SD.SDC_ID]
            state_dict = scenario["tracks"][ego_car_id]["state"]
            valid_track = state_dict["position"][np.where(state_dict["valid"].astype(int))][..., :2]

            dir = valid_track[1:] - valid_track[:-1]
            dir = np.arctan(dir[..., 1] / dir[..., 0])
            curvature = sum(abs(dir[1:] - dir[:-1]) / np.pi) + 1

            sdc_moving_dist = SD.sdc_moving_dist(scenario)
            num_moving_objs = SD.num_moving_object(scenario, object_type=MetaDriveType.VEHICLE)
            return sdc_moving_dist * curvature + num_moving_objs * obj_weight

        self.summary_lookup = sorted(self.summary_lookup, key=lambda scenario_id: _score(scenario_id))
