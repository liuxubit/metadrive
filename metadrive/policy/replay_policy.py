import logging

from metadrive.policy.base_policy import BasePolicy
from metadrive.utils.waymo_utils.parse_object_state import parse_vehicle_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

has_rendered = False

# class ReplayPolicy(BasePolicy):
#     def __init__(self, control_object, locate_info):
#         super(ReplayPolicy, self).__init__(control_object=control_object)
#         self.traj_info = locate_info["traj"]
#         self.start_index = min(self.traj_info.keys())
#         self.init_pos = locate_info["init_pos"]
#         self.heading = locate_info["heading"]
#         self.timestep = 0
#         self.damp = 0
#         # how many times the replay data is slowed down
#         self.damp_interval = 1
#
#     def act(self, *args, **kwargs):
#         self.damp += self.damp_interval
#         if self.damp == self.damp_interval:
#             self.timestep += 1
#             self.damp = 0
#         else:
#             return [0, 0]
#
#         if str(self.timestep) == self.start_index:
#             self.control_object.set_position(self.init_pos)
#         elif str(self.timestep) in self.traj_info.keys():
#             self.control_object.set_position(self.traj_info[str(self.timestep)])
#
#         if self.heading is None or str(self.timestep - 1) not in self.heading.keys():
#             pass
#         else:
#             this_heading = self.heading[str(self.timestep - 1)]
#             self.control_object.set_heading_theta(np.arctan2(this_heading[0], this_heading[1]) - np.pi / 2)
#
#         return [0, 0]


class ReplayEgoCarPolicy(BasePolicy):
    """
    Replay policy from Real data. For adding new policy, overwrite get_trajectory_info()
    This policy is designed for Waymo Policy by default
    """
    def __init__(self, control_object, random_seed):
        super(ReplayEgoCarPolicy, self).__init__(control_object=control_object)
        self.traj_info = self.get_trajectory_info()
        self.start_index = 0
        self.init_pos = self.traj_info[0]["position"]
        self.heading = self.traj_info[0]["heading"]
        self.timestep = 0
        self.damp = 0
        # how many times the replay data is slowed down
        self.damp_interval = 1
        # self.control_object.disable_gravity()

    def get_trajectory_info(self):
        trajectory_data = self.engine.data_manager.get_case(self.engine.global_random_seed)["tracks"]
        sdc_track_index = str(self.engine.data_manager.get_case(self.engine.global_random_seed)["sdc_track_index"])
        return [
            parse_vehicle_state(trajectory_data[sdc_track_index], i)
            for i in range(len(trajectory_data[sdc_track_index]["state"]["position"]))
        ]

    def act(self, *args, **kwargs):
        self.damp += self.damp_interval
        if self.damp == self.damp_interval:
            self.timestep += 1
            self.damp = 0
        else:
            return [0, 0]

        if self.timestep == self.start_index:
            self.control_object.set_position(self.init_pos)
        elif self.timestep < len(self.traj_info):
            self.control_object.set_position(self.traj_info[int(self.timestep)]["position"])
            self.control_object.set_velocity(self.traj_info[int(self.timestep)]["velocity"])

        if self.heading is None or self.timestep >= len(self.traj_info):
            pass
        else:
            this_heading = self.traj_info[int(self.timestep)]["heading"]
            angular_velocity = self.traj_info[int(self.timestep)]["angular_velocity"]
            self.control_object.set_heading_theta(this_heading)
            self.control_object.set_angular_velocity(angular_velocity)

        return [0, 0]


class WaymoReplayEgoCarPolicy(ReplayEgoCarPolicy):
    """
    Replay policy is originally designed for waymo car, so no new changes is required for this class.
    """
    pass


class NuPlanReplayEgoCarPolicy(ReplayEgoCarPolicy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sim_time_interval = self.engine.data_manager.time_interval
        if not self.control_object.config["no_wheel_friction"]:
            logger.warning("\nNOTE:set no_wheel_friction in vehicle config can make the replay more smooth! \n")

        # self.control_object.disable_gravity()

    def get_trajectory_info(self):
        from metadrive.utils.nuplan_utils.parse_object_state import parse_ego_vehicle_state_trajectory
        scenario = self.engine.data_manager.current_scenario
        return parse_ego_vehicle_state_trajectory(scenario, self.engine.current_map.nuplan_center)

    def act(self, *args, **kwargs):
        self.damp += self.damp_interval
        if self.damp == self.damp_interval:
            self.timestep += 1
            self.damp = 0
        else:
            return [0, 0]

        if self.timestep < len(self.traj_info):
            self.control_object.set_position(self.traj_info[int(self.timestep)]["position"])
            if self.timestep < len(self.traj_info) - 1:
                velocity = self.traj_info[int(self.timestep + 1)]["position"] - self.traj_info[int(self.timestep
                                                                                                   )]["position"]
                velocity /= self.sim_time_interval
                self.control_object.set_velocity(velocity, in_local_frame=False)
            else:
                velocity = self.traj_info[int(self.timestep)]["velocity"]
                self.control_object.set_velocity(velocity, in_local_frame=True)
            # self.control_object.set_velocity(self.traj_info[int(self.timestep)]["velocity"])
        if self.heading is None or self.timestep >= len(self.traj_info):
            pass
        else:
            this_heading = self.traj_info[int(self.timestep)]["heading"]
            angular_v = self.traj_info[int(self.timestep)]["angular_velocity"]
            self.control_object.set_heading_theta(this_heading)
            self.control_object.set_angular_velocity(angular_v)

        return [0, 0]


class NuPlanReplayTrafficParticipantPolicy(BasePolicy):
    """
    This policy should be used with TrafficParticipantManager Together
    """
    def __init__(self, control_object, fix_height=None, random_seed=None, config=None):
        super(NuPlanReplayTrafficParticipantPolicy, self).__init__(control_object, random_seed, config)
        self.fix_height = fix_height
        self.timestep = 0
        self.damp = 0
        self.start_index = 0
        # how many times the replay data is slowed down
        self.damp_interval = 1

    def act(self, obj_state, *args, **kwargs):
        self.damp += self.damp_interval
        if self.damp == self.damp_interval:
            self.timestep += 1
            self.damp = 0
        else:
            return [0, 0]
        self.control_object.set_position(obj_state["position"], self.fix_height)
        self.control_object.set_heading_theta(obj_state["heading"])
        self.control_object.set_velocity(obj_state["velocity"])
        return [0, 0]
