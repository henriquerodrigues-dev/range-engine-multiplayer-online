from mathutils import Vector, Matrix
from Range import logic, types, constraints, events
from collections import OrderedDict

def clamp(x, a, b):
    """Clamp x between a and b"""
    return min(max(a, x), b)

class CharacterController(types.KX_PythonComponent):
    # ---------------------- Configurable arguments ----------------------
    args = OrderedDict([
        ("Activate", True),                     # Activate the character
        ("Walk Speed", 2.5),                    # Walking speed (units/sec)
        ("Run Speed", 5.0),                     # Running speed (units/sec)
        ("Max Jumps", 1),                       # Maximum jumps
        ("Avoid Sliding", True),                # Prevent sliding when stopping
        ("Static Jump Direction", False),       # Maintain jump direction
        ("Static Jump Rotation", False),        # Maintain rotation while jumping
        ("Smooth Character Movement", 0.1),    # Movement smoothing (0 = instant, 0.99 = very smooth)
        ("Make Object Invisible", False),       # Make object invisible
    ])

    def start(self, args):
        """Initialize the character controller"""
        self.active = args["Activate"]
        self.walkSpeed = args["Walk Speed"]
        self.runSpeed = args["Run Speed"]
        self.avoidSliding = args["Avoid Sliding"]
        self.staticJump = args["Static Jump Direction"]
        self.staticJumpRot = args["Static Jump Rotation"]

        # ---------------------- Internal state ----------------------
        self.__lastPosition = self.object.worldPosition.copy()
        self.__lastDirection = Vector([0, 0, 0])
        self.__smoothSlidingFlag = False
        self.__smoothMov = clamp(args["Smooth Character Movement"], 0, 0.99)
        self.__smoothVelocity = Vector([0, 0, 0])
        self.__jumpDirection = Vector([0, 0, 0])
        self.__jumpRotation = Matrix.Identity(3)

        # ---------------------- Physics character ----------------------
        self.character = constraints.getCharacter(self.object)
        self.character.maxJumps = args["Max Jumps"]

        # Make the object invisible if needed
        if self.active and args["Make Object Invisible"]:
            self.object.visible = False

    def characterMovement(self):
        """Handle character walking and running with smoothing and delta time"""
        dt = logic.deltaTime()  # Delta time for frame-rate independent movement
        keyboard = logic.keyboard.inputs
        speed = self.runSpeed if keyboard[events.LEFTSHIFTKEY].active else self.walkSpeed

        # ---------------------- Input vector ----------------------
        input_vec = Vector([
            keyboard[events.DKEY].active - keyboard[events.AKEY].active,
            keyboard[events.WKEY].active - keyboard[events.SKEY].active,
            0
        ])

        self.__smoothSlidingFlag = input_vec.length != 0

        if input_vec.length != 0:
            input_vec.normalize()
            input_vec *= speed * dt  # Apply delta time
        else:
            input_vec = Vector([0, 0, 0])

        # ---------------------- Static jump handling ----------------------
        if not self.character.onGround:
            if self.staticJump:
                input_vec = self.__jumpDirection.copy()
            if self.staticJumpRot:
                self.object.worldOrientation = self.__jumpRotation.copy()
        else:
            self.__jumpDirection = input_vec.copy()
            self.__jumpRotation = self.object.worldOrientation.copy()

        # ---------------------- Smooth movement interpolation ----------------------
        smooth_factor = 1.0 - self.__smoothMov
        self.__smoothVelocity = self.__smoothVelocity.lerp(input_vec, smooth_factor)

        # ---------------------- Apply walk direction ----------------------
        self.character.walkDirection = self.object.worldOrientation * self.__smoothVelocity

        # ---------------------- Update last position and direction ----------------------
        if self.__smoothVelocity.length != 0:
            self.__lastDirection = self.object.worldPosition - self.__lastPosition
            self.__lastPosition = self.object.worldPosition.copy()

    def characterJump(self):
        """Handle character jump"""
        keyboard = logic.keyboard.inputs
        keyTAP = logic.KX_INPUT_JUST_ACTIVATED
        if keyTAP in keyboard[events.SPACEKEY].queue:
            self.character.jump()

    def avoidSlide(self):
        """Prevent unwanted sliding when character stops"""
        if not self.__smoothSlidingFlag and self.__smoothVelocity.length > 0:
            target_pos = self.__lastPosition.copy()
            self.object.worldPosition.xy = self.object.worldPosition.xy.lerp(target_pos.xy, 0.5)
            # Reset velocity if last direction differs too much
            if self.__lastDirection.length > 0:
                angle = self.__lastDirection.angle(self.__smoothVelocity)
                if angle > 0.5:
                    self.__smoothVelocity = Vector([0, 0, 0])

    def update(self):
        """Update character movement, jump, and sliding per frame"""
        if not self.active:
            return
        self.characterMovement()
        self.characterJump()
        if self.avoidSliding:
            self.avoidSlide()
