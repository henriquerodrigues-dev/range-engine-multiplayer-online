from mathutils import Vector, Matrix
from Range import logic, types, constraints, events
from collections import OrderedDict


def clamp(x, a, b):
    """Clamp x between a and b"""
    return min(max(a, x), b)


class CharacterController(types.KX_PythonComponent):

    # ---------------------- Configurable arguments ----------------------
    args = OrderedDict([
        ("Activate", True),                     # Enable / disable controller
        ("Walk Speed", 2.5),                    # Walking speed
        ("Run Speed", 5.0),                     # Running speed
        ("Max Jumps", 1),                       # Maximum jumps
        ("Avoid Sliding", True),                # Prevent unwanted sliding
        ("Static Jump Direction", False),       # Lock movement direction in air
        ("Static Jump Rotation", False),        # Lock rotation while jumping
        ("Smooth Character Movement", 0.1),     # Movement smoothing
        ("Make Object Invisible", False),       # Hide player object
    ])

    # ---------------------- Start ----------------------
    def start(self, args):
        """Initialize character controller"""
        self.active = args["Activate"]
        self.walkSpeed = args["Walk Speed"]
        self.runSpeed = args["Run Speed"]
        self.avoidSliding = args["Avoid Sliding"]
        self.staticJump = args["Static Jump Direction"]
        self.staticJumpRot = args["Static Jump Rotation"]

        # ---------------------- Internal movement state ----------------------
        self.__lastPosition = self.object.worldPosition.copy()
        self.__lastDirection = Vector((0, 0, 0))
        self.__smoothSlidingFlag = False
        self.__smoothMov = clamp(args["Smooth Character Movement"], 0, 0.99)
        self.__smoothVelocity = Vector((0, 0, 0))
        self.__jumpDirection = Vector((0, 0, 0))
        self.__jumpRotation = Matrix.Identity(3)

        # ---------------------- Jump state control ----------------------
        self.__jumpTimer = 0.0          # Time since jump started
        self.__minJumpTime = 0.15       # Minimum time in "jumping" state

        # ---------------------- Physics character ----------------------
        self.character = constraints.getCharacter(self.object)
        self.character.maxJumps = args["Max Jumps"]

        # ---------------------- Global player state ----------------------
        self.object["state"] = "idle"

        if self.active and args["Make Object Invisible"]:
            self.object.visible = False

    # ---------------------- Movement ----------------------
    def characterMovement(self):
        """Handle walking / running movement"""
        dt = logic.deltaTime()
        keyboard = logic.keyboard.inputs

        running = keyboard[events.LEFTSHIFTKEY].active
        speed = self.runSpeed if running else self.walkSpeed

        # Input vector (local space)
        input_vec = Vector((
            keyboard[events.DKEY].active - keyboard[events.AKEY].active,
            keyboard[events.WKEY].active - keyboard[events.SKEY].active,
            0
        ))

        self.__smoothSlidingFlag = input_vec.length != 0

        if input_vec.length:
            input_vec.normalize()
            input_vec *= speed * dt
        else:
            input_vec.zero()

        # ---------------------- Jump locking ----------------------
        if not self.character.onGround:
            if self.staticJump:
                input_vec = self.__jumpDirection.copy()
            if self.staticJumpRot:
                self.object.worldOrientation = self.__jumpRotation.copy()
        else:
            self.__jumpDirection = input_vec.copy()
            self.__jumpRotation = self.object.worldOrientation.copy()

        # ---------------------- Smooth interpolation ----------------------
        smooth_factor = 1.0 - self.__smoothMov
        self.__smoothVelocity = self.__smoothVelocity.lerp(input_vec, smooth_factor)

        # Apply movement
        self.character.walkDirection = (
            self.object.worldOrientation * self.__smoothVelocity
        )

        # Track last movement
        if self.__smoothVelocity.length:
            self.__lastDirection = self.object.worldPosition - self.__lastPosition
            self.__lastPosition = self.object.worldPosition.copy()

        # ---------------------- Ground states ----------------------
        if self.character.onGround:
            self.__jumpTimer = 0.0  # Reset jump timer when grounded

            if input_vec.length == 0:
                self.object["state"] = "idle"
            else:
                self.object["state"] = "running" if running else "walking"

    # ---------------------- Jump ----------------------
    def characterJump(self):
        """Handle jump input"""
        keyboard = logic.keyboard.inputs

        if logic.KX_INPUT_JUST_ACTIVATED in keyboard[events.SPACEKEY].queue:
            self.character.jump()
            self.object["state"] = "jumping"
            self.__jumpTimer = 0.0  # Start jump timer

    # ---------------------- Air state ----------------------
    def updateAirState(self):
        """Handle jumping / falling states"""
        if not self.character.onGround:
            dt = logic.deltaTime()
            self.__jumpTimer += dt

            vel_z = self.object.getLinearVelocity().z

            # Force jumping state for a minimum time
            if self.__jumpTimer < self.__minJumpTime:
                self.object["state"] = "jumping"
            else:
                if vel_z > 0.05:
                    self.object["state"] = "jumping"
                else:
                    self.object["state"] = "falling"

    # ---------------------- Avoid sliding ----------------------
    def avoidSlide(self):
        """Prevent character from sliding after stopping"""
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
        """Main update loop"""
        if not self.active:
            return

        self.characterMovement()
        self.characterJump()
        self.updateAirState()

        if self.avoidSliding:
            self.avoidSlide()
