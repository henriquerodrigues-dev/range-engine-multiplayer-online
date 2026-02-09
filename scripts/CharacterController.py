"""
====================================================
CharacterController – Locomotion & Animation States
====================================================

OBJECT VARIABLES (accessible by other scripts):
-----------------------------------------------
object["state"]  -> Estado atual do player (string)
    idle
    walking_front
    walking_back
    walking_strafe_left
    walking_strafe_right
    running_front
    running_back
    running_strafe_left
    running_strafe_right
    jump_idle
    jump_move
    fall_idle
    fall_move

object["speed"]  -> Velocidade normalizada (0.0 – 1.0)

CONFIGURABLE ARGUMENTS (Inspector):
----------------------------------
Activate
Walk Speed
Run Speed
Max Jumps
Avoid Sliding
Static Jump Direction
Static Jump Rotation
Smooth Character Movement
Make Object Invisible

INTERNAL VARIABLES (Runtime):
-----------------------------
__smoothMov            -> fator de suavização
__smoothVelocity       -> velocidade suavizada
__lastPosition         -> posição anterior
__lastDirection        -> última direção válida
__smoothSlidingFlag    -> usado para evitar sliding
__jumpDirection        -> direção salva no pulo
__jumpRotation         -> rotação salva no pulo
__jumpTimer            -> tempo desde início do pulo
__minJumpTime          -> tempo mínimo em estado jump
__jumpMoving           -> indica se pulou em movimento
====================================================
"""

from mathutils import Vector, Matrix
from Range import logic, types, constraints, events
from collections import OrderedDict


def clamp(x, a, b):
    return min(max(a, x), b)


class CharacterController(types.KX_PythonComponent):

    # ---------------------- Configurable arguments ----------------------
    args = OrderedDict([
        ("Activate", True),
        ("Walk Speed", 2.5),
        ("Run Speed", 5.0),
        ("Max Jumps", 1),
        ("Avoid Sliding", True),
        ("Static Jump Direction", False),
        ("Static Jump Rotation", False),
        ("Smooth Character Movement", 0.1),
        ("Make Object Invisible", False),
    ])

    # ---------------------- Start ----------------------
    def start(self, args):
        self.active = args["Activate"]
        self.walkSpeed = args["Walk Speed"]
        self.runSpeed = args["Run Speed"]
        self.avoidSliding = args["Avoid Sliding"]
        self.staticJump = args["Static Jump Direction"]
        self.staticJumpRot = args["Static Jump Rotation"]

        # ---- Movement smoothing ----
        self.__smoothMov = clamp(args["Smooth Character Movement"], 0, 0.99)
        self.__smoothVelocity = Vector((0, 0, 0))
        self.__lastPosition = self.object.worldPosition.copy()
        self.__lastDirection = Vector((0, 0, 0))
        self.__smoothSlidingFlag = False

        # ---- Jump lock ----
        self.__jumpDirection = Vector((0, 0, 0))
        self.__jumpRotation = Matrix.Identity(3)

        # ---- Jump state ----
        self.__jumpTimer = 0.0
        self.__minJumpTime = 0.15
        self.__jumpMoving = False

        # ---- Physics character ----
        self.character = constraints.getCharacter(self.object)
        self.character.maxJumps = args["Max Jumps"]

        # ---- Public object variables ----
        self.object["state"] = "idle"
        self.object["speed"] = 0.0

        if self.active and args["Make Object Invisible"]:
            self.object.visible = False

    # ---------------------- Movement ----------------------
    def characterMovement(self):
        dt = logic.deltaTime()
        keyboard = logic.keyboard.inputs

        running = keyboard[events.LEFTSHIFTKEY].active
        max_speed = self.runSpeed if running else self.walkSpeed
        speed = max_speed

        ix = keyboard[events.DKEY].active - keyboard[events.AKEY].active
        iy = keyboard[events.WKEY].active - keyboard[events.SKEY].active

        input_vec = Vector((ix, iy, 0))
        self.__smoothSlidingFlag = input_vec.length != 0

        if input_vec.length:
            input_vec.normalize()
            input_vec *= speed * dt
        else:
            input_vec.zero()

        # ---- Jump locking ----
        if not self.character.onGround:
            if self.staticJump:
                input_vec = self.__jumpDirection.copy()
            if self.staticJumpRot:
                self.object.worldOrientation = self.__jumpRotation.copy()
        else:
            self.__jumpDirection = input_vec.copy()
            self.__jumpRotation = self.object.worldOrientation.copy()

        # ---- Smooth movement ----
        smooth_factor = 1.0 - self.__smoothMov
        self.__smoothVelocity = self.__smoothVelocity.lerp(input_vec, smooth_factor)
        self.character.walkDirection = (
            self.object.worldOrientation * self.__smoothVelocity
        )

        # ---- Speed (normalized) ----
        current_speed = self.__smoothVelocity.length / max(dt, 0.0001)
        self.object["speed"] = clamp(current_speed / self.runSpeed, 0.0, 1.0)

        # ---- Track movement ----
        if self.__smoothVelocity.length:
            self.__lastDirection = self.object.worldPosition - self.__lastPosition
            self.__lastPosition = self.object.worldPosition.copy()

        # ---- Ground locomotion states ----
        if self.character.onGround:
            self.__jumpTimer = 0.0

            if ix == 0 and iy == 0:
                self.object["state"] = "idle"
                return

            prefix = "running_" if running else "walking_"

            if iy > 0:
                self.object["state"] = prefix + "front"
            elif iy < 0:
                self.object["state"] = prefix + "back"
            elif ix > 0:
                self.object["state"] = prefix + "strafe_right"
            elif ix < 0:
                self.object["state"] = prefix + "strafe_left"

    # ---------------------- Jump ----------------------
    def characterJump(self):
        keyboard = logic.keyboard.inputs
        if logic.KX_INPUT_JUST_ACTIVATED in keyboard[events.SPACEKEY].queue:
            self.__jumpMoving = self.__smoothVelocity.length > 0.01
            self.character.jump()
            self.object["state"] = "jump_move" if self.__jumpMoving else "jump_idle"
            self.__jumpTimer = 0.0

    # ---------------------- Air State ----------------------
    def updateAirState(self):
        if not self.character.onGround:
            dt = logic.deltaTime()
            self.__jumpTimer += dt

            vel_z = self.object.getLinearVelocity().z
            moving = self.__jumpMoving or self.__smoothVelocity.length > 0.01

            if self.__jumpTimer < self.__minJumpTime:
                self.object["state"] = "jump_move" if moving else "jump_idle"
            else:
                if vel_z > 0.05:
                    self.object["state"] = "jump_move" if moving else "jump_idle"
                else:
                    self.object["state"] = "fall_move" if moving else "fall_idle"

    # ---------------------- Avoid sliding ----------------------
    def avoidSlide(self):
        if not self.__smoothSlidingFlag and self.__smoothVelocity.length > 0:
            target = self.__lastPosition.copy()
            self.object.worldPosition.xy = self.object.worldPosition.xy.lerp(
                target.xy, 0.5
            )

            if self.__lastDirection.length > 0:
                if self.__lastDirection.angle(self.__smoothVelocity) > 0.5:
                    self.__smoothVelocity.zero()

    # ---------------------- Update ----------------------
    def update(self):
        if not self.active:
            return

        self.characterMovement()
        self.characterJump()
        self.updateAirState()

        if self.avoidSliding:
            self.avoidSlide()
