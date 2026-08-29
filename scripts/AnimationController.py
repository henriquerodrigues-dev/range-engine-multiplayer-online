"""AnimationController - traduz o estado publicado pelo CharacterController em actions do armature."""

from collections import OrderedDict

from Range import logic, types


def clamp(value, low, high):
    return min(max(value, low), high)


class AnimationController(types.KX_PythonComponent):

    args = OrderedDict([
        ("Activate", True),
        ("Armature Name", ""),
        ("Anim Layer", 0),
        ("Overlay Layer", 1),
        ("Overlay Blend", 8.0),
        ("Walk Speed Scale", 1.0),
        ("Run Speed Scale", 1.0),
        ("Min Speed Scale", 0.3),

        ("Idle Action", "player-idle"),
        ("Idle Start", 1),
        ("Idle End", 247),
        ("Idle Blend", 8.0),

        ("Walk Action", "player-walking"),
        ("Walk Start", 1),
        ("Walk End", 32),
        ("Walk Blend", 8.0),

        ("Walk Back Action", "player-walking-back"),
        ("Walk Back Start", 1),
        ("Walk Back End", 38),
        ("Walk Back Blend", 8.0),

        ("Run Action", "player-running"),
        ("Run Start", 1),
        ("Run End", 22),
        ("Run Blend", 8.0),

        ("Run Back Action", "player-running-back"),
        ("Run Back Start", 1),
        ("Run Back End", 20),
        ("Run Back Blend", 8.0),

        ("Jump Action", "player-jump-running"),
        ("Jump Start", 1),
        ("Jump End", 30),
        ("Jump Blend", 4.0),

        ("Fall Action", "player-fall"),
        ("Fall Start", 1),
        ("Fall End", 30),
        ("Fall Blend", 4.0),

        ("Debug", False),
    ])

    IDLE = "idle"
    SPEED_EPSILON = 0.05

    CLIP_SETUP = (
        ("idle", "Idle", False),
        ("walk", "Walk", False),
        ("walk_back", "Walk Back", False),
        ("run", "Run", False),
        ("run_back", "Run Back", False),
        ("jump", "Jump", True),
        ("fall", "Fall", False),
    )

    DIRECTIONS = ("front", "front_left", "front_right", "strafe_left",
                  "strafe_right", "back", "back_left", "back_right")

    def start(self, args):
        self.active = args["Activate"]
        self.layer = int(args["Anim Layer"])
        self.overlay_layer = int(args["Overlay Layer"])
        self.overlay_blend = max(float(args["Overlay Blend"]), 0.0)
        self.min_speed_scale = max(float(args["Min Speed Scale"]), 0.01)
        self.debug = args["Debug"]

        self.play_modes = {
            "loop": logic.KX_ACTION_MODE_LOOP,
            "once": logic.KX_ACTION_MODE_PLAY,
            "ping_pong": logic.KX_ACTION_MODE_PING_PONG,
        }

        self.clips = self.buildClips(args)
        self.states = self.buildStates(float(args["Walk Speed Scale"]),
                                       float(args["Run Speed Scale"]))
        self.armature = self.findArmature(args["Armature Name"])

        self.idle_state = self.states[self.IDLE]
        self.current_state = None
        self.current_clip = None
        self.current_speed = 1.0
        self.current_jumps = 0

        if self.armature is None:
            self.active = False
            print("[AnimationController] armature nao encontrada em '%s'." % self.object.name)
        elif not self.clips["idle"][0]:
            self.active = False
            print("[AnimationController] 'Idle Action' nao pode ficar vazio.")

    def buildClips(self, args):
        clips = {}
        for key, prefix, once in self.CLIP_SETUP:
            clips[key] = (str(args[prefix + " Action"]).strip(),
                          int(args[prefix + " Start"]),
                          int(args[prefix + " End"]),
                          self.play_modes["once" if once else "loop"],
                          max(float(args[prefix + " Blend"]), 0.0),
                          once)
        return clips

    def buildStates(self, walk_scale, run_scale):
        states = {self.IDLE: ("idle", None)}

        for direction in self.DIRECTIONS:
            back = direction.startswith("back")
            states["walking_" + direction] = ("walk_back" if back else "walk", walk_scale)
            states["running_" + direction] = ("run_back" if back else "run", run_scale)

        for state in ("jump_idle", "jump_move"):
            states[state] = ("jump", None)
        for state in ("fall_idle", "fall_move"):
            states[state] = ("fall", None)

        for state, (clip, scale) in list(states.items()):
            if not self.clips[clip][0]:
                states[state] = ("idle", scale)

        return states

    def findArmature(self, name=""):
        candidates = list(self.object.childrenRecursive) + [self.object]

        if name:
            for obj in candidates:
                if obj.name == name:
                    return obj

        for obj in candidates:
            if isinstance(obj, types.BL_ArmatureObject):
                return obj

        return None

    def play(self, clip, speed, blend, frame=None):
        action, start, end, mode, _, _ = self.clips[clip]
        self.armature.playAction(action, start, end,
                                 layer=self.layer,
                                 blendin=blend,
                                 play_mode=mode,
                                 speed=speed)
        if frame is not None:
            self.armature.setActionFrame(frame, self.layer)

        self.current_speed = speed
        if self.debug:
            print("[AnimationController] %s -> %s (speed %.2f)" % (self.current_state, action, speed))

    def playOverlay(self, action, start, end, mode="once", blend=None, weight=1.0):
        if self.armature is None:
            return
        self.armature.playAction(action, start, end,
                                 layer=self.overlay_layer,
                                 blendin=self.overlay_blend if blend is None else blend,
                                 play_mode=self.play_modes.get(mode, self.play_modes["once"]),
                                 layer_weight=clamp(1.0 - weight, 0.0, 1.0))

    def stopOverlay(self):
        if self.armature is not None:
            self.armature.stopAction(self.overlay_layer)

    def isOverlayPlaying(self):
        return self.armature is not None and self.armature.isPlayingAction(self.overlay_layer)

    def update(self):
        if not self.active:
            return

        state = self.object.get("state", self.IDLE)
        clip, scale = self.states.get(state, self.idle_state)
        entry = self.clips[clip]
        blend, once = entry[4], entry[5]

        if scale is None:
            speed = 1.0
        else:
            ratio = clamp(float(self.object.get("speed", 1.0)), 0.0, 1.0)
            speed = scale * max(ratio, self.min_speed_scale)

        jumps = self.object.get("jump_count", 0)
        retrigger = once and jumps > self.current_jumps
        new_clip = clip != self.current_clip

        self.current_jumps = jumps
        self.current_state = state
        self.current_clip = clip

        if new_clip or retrigger:
            self.play(clip, speed, blend if new_clip else 0.0)
        elif not once and not self.armature.isPlayingAction(self.layer):
            self.play(clip, speed, 0.0)
        elif abs(speed - self.current_speed) > self.SPEED_EPSILON:
            self.play(clip, speed, 0.0, self.armature.getActionFrame(self.layer))
