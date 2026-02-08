from Range import logic, types, render
from collections import OrderedDict
from mathutils import Vector, Matrix

class ThirdPersonCamera(types.KX_PythonComponent):
    # ---------------------- Configurable arguments ----------------------
    args = OrderedDict([
        ("Activate", True),                     # Activate the camera
        ("Mouse Sensibility", 2.0),             # Mouse sensitivity
        ("Invert Mouse X Axis", False),         # Invert X axis
        ("Invert Mouse Y Axis", False),         # Invert Y axis
        ("Camera Height", 1.5),                 # Camera height above player
        ("Camera Distance", 5.0),               # Distance from player
        ("Camera Crab (Side)", 0.6),            # Lateral offset
        ("Camera Collision", True),             # Enable collision detection
        ("Camera Collision Property", "ground"),# Collision property
        ("Align Player to View", {"Never", "On Player Movement", "Always"}), # Player alignment mode
        ("Align Player Smooth", 0.7),           # Player rotation smoothing
        ("Rotation Smooth", 0.05),              # Camera rotation smoothing
        ("Position Smooth", 0.3),               # Camera position smoothing
    ])

    def start(self, args):
        """Initialize camera settings"""
        self.active = args["Activate"]
        self.mouse_sens = args["Mouse Sensibility"] * -0.001
        self.invert_x = -1 if args["Invert Mouse X Axis"] else 1
        self.invert_y = -1 if args["Invert Mouse Y Axis"] else 1

        self.camera_pos = Vector([0, 0, 0])
        self.set_camera_pos(args["Camera Crab (Side)"], -args["Camera Distance"], args["Camera Height"])

        self.camera_collision = args["Camera Collision"]
        self.camera_collision_prop = args["Camera Collision Property"]

        self.cam_align = []
        self.set_camera_align(args["Align Player to View"])
        self.cam_align_smooth = args["Align Player Smooth"]

        self.rotation_smooth = args["Rotation Smooth"]
        self.position_smooth = args["Position Smooth"]

        self.current_pan = 0.0
        self.current_tilt = 0.0
        self.smoothed_pos = self.object.worldPosition.copy()

        # Error if camera has no parent
        self.error = self.object.parent is None
        if self.error:
            print("[Third Person Camera] Error: The camera must be parented to an object.")

        self.camera_pan = Matrix.Identity(3)
        self.camera_tilt = Matrix.Identity(3)

        w, h = render.getWindowWidth(), render.getWindowHeight()
        self.prev_mouse_pos = Vector([w/2, h/2])
        render.setMousePosition(int(self.prev_mouse_pos[0]), int(self.prev_mouse_pos[1]))

        self.player_pos = None
        if not self.error:
            self.player_pos = self.object.parent.worldPosition.copy()

    # ---------------------- Camera rotation ----------------------
    def pan(self, angle):
        """Smooth horizontal rotation"""
        self.current_pan += (angle - self.current_pan) * self.rotation_smooth
        euler = self.camera_pan.to_euler()
        euler[2] += self.current_pan
        self.camera_pan = euler.to_matrix()

    def tilt(self, angle):
        """Smooth vertical rotation"""
        self.current_tilt += (angle - self.current_tilt) * self.rotation_smooth
        euler = self.camera_tilt.to_euler()
        euler[0] += self.current_tilt
        self.camera_tilt = euler.to_matrix()

    # ---------------------- Camera position ----------------------
    def get_world_camera_pos(self):
        """Compute world position based on tilt, pan, and offset"""
        pos = self.camera_pos.copy()
        pos = self.camera_tilt * pos
        pos = self.camera_pan * pos
        return self.object.parent.worldPosition + pos

    def limit_camera_rotation(self):
        """Prevent vertical flip"""
        euler = self.camera_tilt.to_euler()
        euler[0] = max(min(euler[0], 1.4), -1.4)
        self.camera_tilt = euler.to_matrix()

    def is_player_moving(self):
        """Check if player moved since last frame"""
        if self.player_pos is None:
            return False
        delta = self.player_pos - self.object.parent.worldPosition.copy()
        moving = delta.length > 0.001
        self.player_pos = self.object.parent.worldPosition.copy()
        return moving

    def apply_camera_position(self):
        """Set camera position, apply collision and smoothing"""
        cam_pos = self.get_world_camera_pos()

        if self.camera_collision:
            target = self.object.parent.worldPosition + Vector([0, 0, self.camera_pos[2] * 0.5])
            hit, hit_pos, _ = self.object.rayCast(target, cam_pos, 0, self.camera_collision_prop, 1, 0, 0)
            if hit:
                cam_pos = hit_pos

        # Smooth position
        self.smoothed_pos = self.smoothed_pos.lerp(cam_pos, self.position_smooth)
        self.object.worldPosition = self.smoothed_pos

        # Camera orientation
        view_dir = self.camera_tilt * Vector([0, 1, 0])
        view_dir = self.camera_pan * view_dir
        self.object.lookAt([0, 0, 1], 1, 1)
        self.object.lookAt(view_dir * -1, 2, 1)

    # ---------------------- Helper functions ----------------------
    def set_camera_align(self, align_type):
        self.cam_align = {
            "Never": [0, 0],
            "On Player Movement": [0, 1],
            "Always": [1, 1]
        }[align_type]

    def set_camera_pos(self, x, y, z):
        self.camera_pos = Vector([x, y, z])

    def mouselook(self):
        """Rotate camera based on mouse input"""
        wSize = Vector([render.getWindowWidth(), render.getWindowHeight()])
        wCenter = Vector([int(wSize[0] * 0.5), int(wSize[1] * 0.5)])

        mPos = Vector(logic.mouse.position)
        mPos[0] = int(mPos[0] * wSize[0])
        mPos[1] = int(mPos[1] * wSize[1])

        render.setMousePosition(int(wCenter[0]), int(wCenter[1]))

        mDisp = (mPos - wCenter) * self.mouse_sens
        mDisp[0] *= self.invert_x
        mDisp[1] *= self.invert_y
        
        self.pan(mDisp[0])
        self.tilt(mDisp[1])
        self.limit_camera_rotation()

    def align_player_to_view(self):
        """Align player smoothly to camera view"""
        target_dir = self.get_camera_view()
        self.object.parent.lookAt(target_dir, 1, 1.0 - self.cam_align_smooth)
        self.object.parent.lookAt([0, 0, 1], 2, 1)

    def get_camera_view(self):
        """Return forward direction of camera in world space"""
        return self.camera_pan * Vector([0, 1, 0])

    def update(self):
        """Update camera every frame"""
        if not self.active or self.error:
            return
        self.mouselook()
        if self.cam_align[self.is_player_moving()]:
            self.align_player_to_view()
        self.apply_camera_position()
