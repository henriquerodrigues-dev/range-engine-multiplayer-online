"""
AnimationController.py

- Sistema para animações Mixamo
- Compatível com 8 direções reais
- Não controla rotação (somente animação)
"""

from Range import logic, types
from collections import OrderedDict


class AnimationController(types.KX_PythonComponent):

    args = OrderedDict([
        ("Blend Time", 8.0),
        ("Anim Layer", 0),
        ("Run Speed Scale", 1.0),
        ("Walk Speed Scale", 1.0),
    ])

    # ---------------------------------------------------
    # START
    # ---------------------------------------------------
    def start(self, args):

        self.blend_time = args.get("Blend Time", 8.0)
        self.layer = args.get("Anim Layer", 0)
        self.run_speed_scale = args.get("Run Speed Scale", 1.0)
        self.walk_speed_scale = args.get("Walk Speed Scale", 1.0)

        self.last_state = None
        self.armature = self.findArmature()

        # ---------- Animações ----------
        self.animations = {

            # IDLE
            "idle": ("player-idle", 1, 247),

            # WALK
            "walking_front": ("player-walking", 1, 32),
            "walking_back": ("player-walking-back", 1, 38),
            "walking_strafe_left": ("player-walking", 1, 32),
            "walking_strafe_right": ("player-walking", 1, 32),
            "walking_front_left": ("player-walking", 1, 32),
            "walking_front_right": ("player-walking", 1, 32),
            "walking_back_left": ("player-walking-back", 1, 38),
            "walking_back_right": ("player-walking-back", 1, 38),

            # RUN
            "running_front": ("player-running", 1, 22),
            "running_back": ("player-running-back", 1, 20),
            "running_strafe_left": ("player-running", 1, 22),
            "running_strafe_right": ("player-running", 1, 22),
            "running_front_left": ("player-running", 1, 22),
            "running_front_right": ("player-running", 1, 22),
            "running_back_left": ("player-running-back", 1, 20),
            "running_back_right": ("player-running-back", 1, 20),

            # AIR
            "jump_idle": ("player-jump", 1, 30),
            "jump_move": ("player-jump", 1, 30),
            "fall_idle": ("player-fall", 1, 30),
            "fall_move": ("player-fall", 1, 30),
        }

    # ---------------------------------------------------
    # FIND ARMATURE
    # ---------------------------------------------------
    def findArmature(self):

        for child in self.object.childrenRecursive:
            if child.name.lower() in ("armature", "player-armature"):
                return child

        for child in self.object.childrenRecursive:
            if getattr(child, "armature", False):
                return child

        if getattr(self.object, "armature", False):
            return self.object

        print("[AnimationController] ERRO: Armature não encontrada!")
        return None

      # ---------------------------------------------------
    # UPDATE
    # ---------------------------------------------------
    def update(self):

        if not self.armature:
            return

        state = self.object.get("state")
        if not state:
            return

        if state not in self.animations:
            return

        anim_name, start, end = self.animations[state]
        obj_speed = self.object.get("speed", 1.0)

        # -------- Speed Scaling --------
        if state.startswith("running"):
            speed = self.run_speed_scale * obj_speed
        elif state.startswith("walking"):
            speed = self.walk_speed_scale * obj_speed
        else:
            speed = 1.0

        if speed < 0.05:
            speed = 0.05

        current_action = self.armature.getActionName(self.layer)

        # 🔥 Se a action for a mesma, não reinicia
        if current_action == anim_name:
            return

        # ---- Troca animação ----
        self.armature.playAction(
            anim_name,
            int(start),
            int(end),
            int(self.layer),
            0,
            int(self.blend_time),
            logic.KX_ACTION_MODE_LOOP,
            speed
        )
