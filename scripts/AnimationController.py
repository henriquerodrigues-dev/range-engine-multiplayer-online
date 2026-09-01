"""AnimationController - traduz o estado publicado pelo CharacterController em actions do armature.

Clip com "Action" em branco nao toca nada: o componente nao mexe na layer e deixa a
animacao anterior seguir, em vez de cair no idle.

Cada clip tem seu bloco de 5 campos - Action, Start Frame, End Frame, Speed e
Blend Frames. Velocidade final:

    Speed * Speed Multiplier * (ratio de velocidade, se o clip acompanha o movimento)

Publica 'anim_clip', 'anim_action', 'anim_frame' e 'anim_speed' para outros scripts.
"""

from collections import OrderedDict, namedtuple

from Range import logic, types


Clip = namedtuple("Clip", "action start end speed blend mode once follows_velocity")


def clamp(value, low, high):
    return min(max(value, low), high)


class AnimationController(types.KX_PythonComponent):

    args = OrderedDict([
        # Componente
        ("Activate", True),
        ("Debug", False),

        # Armature
        ("Armature Name", ""),
        ("Action Layer", 0),

        # Playback
        ("Speed Multiplier", 1.0),
        ("Match Movement Speed", True),
        ("Min Velocity Ratio", 0.3),
        ("Speed Smooth", 0.6),
        ("Speed Step", 0.05),

        # Clips ("Action" em branco desliga o clip)
        ("Idle Action", "player-idle"),
        ("Idle Start Frame", 1),
        ("Idle End Frame", 247),
        ("Idle Speed", 1.0),
        ("Idle Blend Frames", 8.0),

        ("Walking Action", "player-walking"),
        ("Walking Start Frame", 1),
        ("Walking End Frame", 32),
        ("Walking Speed", 1.0),
        ("Walking Blend Frames", 8.0),

        ("Walking Back Action", "player-walking-back"),
        ("Walking Back Start Frame", 1),
        ("Walking Back End Frame", 38),
        ("Walking Back Speed", 1.0),
        ("Walking Back Blend Frames", 8.0),

        ("Running Action", "player-running"),
        ("Running Start Frame", 1),
        ("Running End Frame", 22),
        ("Running Speed", 1.0),
        ("Running Blend Frames", 8.0),

        ("Running Back Action", "player-running-back"),
        ("Running Back Start Frame", 1),
        ("Running Back End Frame", 20),
        ("Running Back Speed", 1.0),
        ("Running Back Blend Frames", 8.0),

        ("Jumping Action", "player-jump-running"),
        ("Jumping Start Frame", 1),
        ("Jumping End Frame", 30),
        ("Jumping Speed", 1.0),
        ("Jumping Blend Frames", 4.0),

        ("Falling Action", "player-fall"),
        ("Falling Start Frame", 1),
        ("Falling End Frame", 30),
        ("Falling Speed", 1.0),
        ("Falling Blend Frames", 4.0),

        ("Falling To Landing Action", ""),
        ("Falling To Landing Start Frame", 1),
        ("Falling To Landing End Frame", 30),
        ("Falling To Landing Speed", 1.0),
        ("Falling To Landing Blend Frames", 4.0),
    ])

    REFERENCE_FPS = 60.0

    CLIP_SETUP = (
        ("idle", "Idle", False, False),
        ("walking", "Walking", False, True),
        ("walking_back", "Walking Back", False, True),
        ("running", "Running", False, True),
        ("running_back", "Running Back", False, True),
        ("jumping", "Jumping", True, False),
        ("falling", "Falling", False, False),
        ("landing", "Falling To Landing", True, False),
    )

    STATE_SETUP = (
        ("idle", "idle", "idle"),
        ("walking", "walking", "walking_back"),
        ("running", "running", "running_back"),
        ("jump", "jumping", "jumping"),
        ("fall", "falling", "falling"),
        ("landing", "landing", "landing"),
    )

    def start(self, args):
        self.active = args["Activate"]
        self.debug = args["Debug"]

        self.layer = int(args["Action Layer"])

        self.speed_multiplier = max(float(args["Speed Multiplier"]), 0.0)
        self.match_movement = args["Match Movement Speed"]
        self.min_velocity_ratio = clamp(float(args["Min Velocity Ratio"]), 0.0, 1.0)
        self.speed_smooth = clamp(float(args["Speed Smooth"]), 0.0, 0.99)
        self.speed_step = max(float(args["Speed Step"]), 0.001)

        self.clips = self.buildClips(args)
        self.states = self.buildStates()
        self.armature = self.findArmature(args["Armature Name"])

        self.idle_state = self.states["idle"]
        self.current_clip = None
        self.current_speed = 1.0
        self.play_speed = 1.0
        self.current_jumps = 0

        if self.armature is None:
            self.active = False
            print("[AnimationController] armature nao encontrada em '%s'." % self.object.name)
            return

        if self.debug:
            self.log("armature='%s'  layer=%d  multiplier=%.2f  match_movement=%s"
                     % (self.armature.name, self.layer, self.speed_multiplier,
                        self.match_movement))
            self.log("min_ratio=%.2f  speed_smooth=%.2f  speed_step=%.3f"
                     % (self.min_velocity_ratio, self.speed_smooth, self.speed_step))
            for key, prefix, _, follows in self.CLIP_SETUP:
                clip = self.clips[key]
                if not clip.action:
                    self.log("  %-13s DESLIGADO ('%s Action' em branco)" % (key, prefix))
                    continue
                self.log("  %-13s '%s' %d-%d  speed=%.2f  blend=%.1f  %s%s"
                         % (key, clip.action, clip.start, clip.end, clip.speed,
                            clip.blend, "once" if clip.once else "loop",
                            "  segue velocidade" if follows else ""))

    def log(self, message):
        print("[AnimationController] %s" % message)

    def buildClips(self, args):
        clips = {}
        for key, prefix, once, follows in self.CLIP_SETUP:
            clips[key] = Clip(
                action=str(args[prefix + " Action"]).strip(),
                start=int(args[prefix + " Start Frame"]),
                end=int(args[prefix + " End Frame"]),
                speed=max(float(args[prefix + " Speed"]), 0.0),
                blend=max(float(args[prefix + " Blend Frames"]), 0.0),
                mode=logic.KX_ACTION_MODE_PLAY if once else logic.KX_ACTION_MODE_LOOP,
                once=once,
                follows_velocity=follows)
        return clips

    def buildStates(self):
        states = {}
        for state, front, back in self.STATE_SETUP:
            states[state] = (self.resolveClip(front), self.resolveClip(back))
        return states

    def resolveClip(self, clip):
        """Clip sem nome de action preenchido nao vira animacao."""
        return clip if self.clips[clip].action else None

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

    def smoothFactor(self, smooth, dt):
        """Converte 'quantidade de suavizacao' (0 = instantaneo) em fator de lerp do frame."""
        if smooth <= 0.0:
            return 1.0
        return clamp(1.0 - pow(smooth, dt * self.REFERENCE_FPS), 0.0, 1.0)

    def targetSpeed(self, clip):
        speed = clip.speed * self.speed_multiplier

        if clip.follows_velocity and self.match_movement:
            ratio = clamp(float(self.object.get("speed", 1.0)), 0.0, 1.0)
            speed *= max(ratio, self.min_velocity_ratio)

        return speed

    def play(self, key, speed, blend, frame=None, reason=""):
        clip = self.clips[key]
        self.armature.playAction(clip.action, clip.start, clip.end,
                                 layer=self.layer,
                                 blendin=blend,
                                 play_mode=clip.mode,
                                 speed=speed)
        if frame is not None:
            self.armature.setActionFrame(frame, self.layer)

        self.current_speed = speed
        if self.debug and reason:
            self.log("%-9s %-13s -> '%s'  speed=%.2f  blend=%.1f"
                     % (reason, key, clip.action, speed, blend))

    def publish(self, key):
        """Expoe o que esta tocando para outros scripts (rede, VFX, IK...)."""
        playing = self.armature.isPlayingAction(self.layer)
        self.object["anim_clip"] = key
        self.object["anim_action"] = self.armature.getActionName(self.layer) if playing else ""
        self.object["anim_frame"] = self.armature.getActionFrame(self.layer) if playing else 0.0
        self.object["anim_speed"] = self.play_speed

    def update(self):
        if not self.active:
            return

        dt = logic.deltaTime()
        state = self.states.get(self.object.get("state"), self.idle_state)
        key = state[1] if self.object.get("moving_back") else state[0]

        if key is None:
            self.publish("")
            return

        clip = self.clips[key]
        target = self.targetSpeed(clip)

        jumps = self.object.get("jump_count", 0)
        retrigger = clip.once and jumps > self.current_jumps
        new_clip = key != self.current_clip

        self.current_jumps = jumps
        self.current_clip = key

        if new_clip or retrigger:
            self.play_speed = target
            self.play(key, target, clip.blend if new_clip else 0.0,
                      reason="troca" if new_clip else "retrigger")
        else:
            self.play_speed += (target - self.play_speed) * self.smoothFactor(self.speed_smooth, dt)

            if not clip.once and not self.armature.isPlayingAction(self.layer):
                self.play(key, self.play_speed, 0.0, reason="reinicio")
            elif abs(self.play_speed - self.current_speed) > self.speed_step:
                # Sem API para mudar a velocidade de uma action em curso: reinicia
                # preservando o frame. 'Speed Step' controla a frequencia disso.
                self.play(key, self.play_speed, 0.0,
                          frame=self.armature.getActionFrame(self.layer))

        self.publish(key)
