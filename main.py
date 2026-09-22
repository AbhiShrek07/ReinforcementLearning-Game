from __future__ import annotations

import random
from enum import Enum, auto
from typing import Optional

from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    CardMaker,
    CollisionRay,
    DirectionalLight,
    Fog,
    LineSegs,
    LPoint3f,
    LVector3f,
    NodePath,
    Plane,
    Point3,
    TextNode,
    Texture,
    TextureStage,
    Vec3,
)

from ai_learning import AITrainer
from battle_system import BattleSystem
from camera_controller import CameraController
from units import (
    AIArmy,
    PlayerArmy,
    Soldier,
    Tank,
    random_position_in_range,
)


class GamePhase(Enum):
    BUY_AND_DEPLOY_PLAYER = auto()
    DEPLOY_AI = auto()
    BATTLE = auto()
    RESULT = auto()


class GameManager(ShowBase):
    """Top-level game class handling phases, input, UI, and integration."""

    def __init__(self) -> None:
        ShowBase.__init__(self)

        # Use manual camera control.
        self.disableMouse()

        # Battlefield extents and deployment zones.
        self.map_half_size = 500.0  # Massive map
        self.player_x_min = -480.0
        self.player_x_max = -40.0
        self.ai_x_min = 40.0
        self.ai_x_max = 480.0
        self.y_min = -480.0
        self.y_max = 480.0

        # Economy - UEBS2 scale
        self.starting_points = 50000
        self.points_remaining = self.starting_points

        # Armies and systems.
        self.player_army = PlayerArmy()
        self.ai_army = AIArmy()
        self.battle_system = BattleSystem(self.player_army, self.ai_army, max_battle_time=300.0)
        self.ai_trainer = AITrainer()

        self.current_phase: GamePhase = GamePhase.BUY_AND_DEPLOY_PLAYER
        self.battle_timer: float = 0.0

        # For AI learning.
        self._ai_round_state = None
        self._ai_round_action: Optional[str] = None

        # Scene setup
        self._setup_camera()
        self._setup_lighting()
        self._create_terrain()
        self._add_scenery()

        # Drag selection state for mass spawning
        self._dragging: bool = False
        self._drag_start_pos: Optional[Point3] = None
        self._current_spawn_type: str = "soldier"
        self._drag_rect_np: Optional[NodePath] = None

        # Camera controller (RTS style).
        self.camera_controller = CameraController(self)

        # Input bindings for unit placement and phase changes.
        self._setup_controls()

        # UI
        self._setup_ui()

        # Schedule main loop.
        self.taskMgr.add(self._update_task, "update-task")

    # ------------------------------------------------------------------
    # Scene / camera
    # ------------------------------------------------------------------
    def _setup_camera(self) -> None:
        # Classic isometric angled view (not purely top-down)
        self.camera.setPos(0, -120, 70)
        self.camera.lookAt(0, 0, 0)
        self.camLens.setFar(3000) # Reset to standard far plane

    def _setup_lighting(self) -> None:
        self.render.setShaderAuto()
        
        ambient = AmbientLight("ambient")
        ambient.setColor((0.8, 0.8, 0.8, 1)) # Softer light
        ambient_np = self.render.attachNewNode(ambient)
        self.render.setLight(ambient_np)

        sun = DirectionalLight("sun")
        sun.setColor((0.9, 0.9, 0.9, 1)) 
        sun_np = self.render.attachNewNode(sun)
        sun_np.setHpr(-45, -60, 0)
        self.render.setLight(sun_np)
        
        # Simple fog for basic depth
        myFog = Fog("Scene Fog")
        myFog.setColor(0.6, 0.7, 0.9)
        myFog.setLinearRange(100, 2000) 
        self.render.setFog(myFog)
        self.setBackgroundColor(0.6, 0.7, 0.9)

    def _create_terrain(self) -> None:
        """Create a textured ground to look more real."""
        cm = CardMaker("ground")
        ground_size = 1100.0 # Just slightly overlaps the 1000m battlefield
        cm.setFrame(-ground_size/2, ground_size/2, -ground_size/2, ground_size/2)
        ground = self.render.attachNewNode(cm.generate())
        ground.setP(-90)
        ground.setPos(0, 0, 0)
        
        try:
            # 1. Base Layer: Uniform Grass 
            tex_grass = self.loader.loadTexture("models/uniform_grass.png")
            tex_grass.setWrapU(Texture.WM_repeat)
            tex_grass.setWrapV(Texture.WM_repeat)
            tex_grass.setAnisotropicDegree(16)
            
            ts_grass = TextureStage("grass_layer")
            ground.setTexture(ts_grass, tex_grass)
            grass_repeat = ground_size * 0.8
            ground.setTexScale(ts_grass, grass_repeat, grass_repeat)
            ground.setTexRotate(ts_grass, 13)
            
            # 2. Mask Layer: Terrain Noise
            # Passing the filename twice tells Panda to use the image's luminance as the ALPHA channel.
            tex_noise = self.loader.loadTexture("models/terrain_noise.png", "models/terrain_noise.png")
            tex_noise.setWrapU(Texture.WM_repeat)
            tex_noise.setWrapV(Texture.WM_repeat)
            
            ts_mask = TextureStage("mask_layer")
            ts_mask.setCombineRgb(TextureStage.CMReplace, TextureStage.CSPrevious, TextureStage.COSrcColor)
            # We now use COSrcAlpha safely without triggering the OpenGL assertion
            ts_mask.setCombineAlpha(TextureStage.CMReplace, TextureStage.CSTexture, TextureStage.COSrcAlpha)
            ground.setTexture(ts_mask, tex_noise)
            # Stretch the noise hugely so mud appears in vast, natural patches
            ground.setTexScale(ts_mask, ground_size / 600.0, ground_size / 600.0)
            ground.setTexRotate(ts_mask, 73)
            
            # 3. Mud Layer: War-torn muddy tracks
            # Interpolates between the Mud and Grass(Previous) based on the mask alpha from stage 2
            tex_mud = self.loader.loadTexture("muddy_battlefield.png")
            tex_mud.setWrapU(Texture.WM_repeat)
            tex_mud.setWrapV(Texture.WM_repeat)
            tex_mud.setAnisotropicDegree(16)
            
            ts_mud = TextureStage("mud_layer")
            ts_mud.setCombineRgb(
                TextureStage.CMInterpolate, 
                TextureStage.CSTexture, TextureStage.COSrcColor,   # High Alpha -> Mud
                TextureStage.CSPrevious, TextureStage.COSrcColor,  # Low Alpha  -> Grass
                TextureStage.CSPrevious, TextureStage.COSrcAlpha   # Alpha Mask from Stage 2
            )
            ground.setTexture(ts_mud, tex_mud)
            # Keep muddy features correctly small (0.6x = ~2 unit wide tank tracks)
            mud_repeat = ground_size * 0.6
            ground.setTexScale(ts_mud, mud_repeat, mud_repeat)
            ground.setTexRotate(ts_mud, 15)

            # Reset color scale for unmodulated, interpolated textures
            ground.setColorScale(1.0, 1.0, 1.0, 1.0)
        except Exception as e:
            print(f"Failed to load terrain texture: {e}")
            ground.setColor(0.3, 0.4, 0.2, 1) # Fallback to grass color

    def _add_scenery(self) -> None:
        """Add scattered stones and block-style procedural trees."""
        stones_parent = self.render.attachNewNode("stones")
        trees_parent = self.render.attachNewNode("trees")
        
        try:
            stone_master = self.loader.loadModel("models/rock_on_ground.glb")
        except Exception:
            stone_master = None
            
        tree_master = NodePath("tree_master")
        try:
            # Trunk
            trunk = self.loader.loadModel("models/box")
            trunk.reparentTo(tree_master)
            trunk.setScale(0.8, 0.8, 4.0)
            trunk.setPos(0, 0, 2.0)
            trunk.setColor(0.3, 0.15, 0.05, 1.0) # Dark brown
            
            # Lower Leaves
            leaves1 = self.loader.loadModel("models/box")
            leaves1.reparentTo(tree_master)
            leaves1.setScale(3.5, 3.5, 3.0)
            leaves1.setPos(0, 0, 5.5)
            leaves1.setColor(0.1, 0.35, 0.1, 1.0) # Pine green
            
            # Upper Leaves
            leaves2 = self.loader.loadModel("models/box")
            leaves2.reparentTo(tree_master)
            leaves2.setScale(2.0, 2.0, 3.0)
            leaves2.setPos(0, 0, 8.5)
            leaves2.setColor(0.12, 0.4, 0.12, 1.0)
            
            tree_master.flattenLight() # Optimize into unified geometry
        except Exception:
            tree_master = None

        ground_half = 500.0
        from units import SceneryObstacle
        
        if stone_master:
            # Scattered stones
            for _ in range(150):
                x = random.uniform(-ground_half, ground_half)
                y = random.uniform(-ground_half, ground_half)
                
                s = stone_master.copyTo(stones_parent)
                s.setPos(x, y, 0)
                s.setH(random.uniform(0, 360))
                # Add a few massive rocks, but mostly small ones
                if random.random() < 0.1:
                    scale = random.uniform(1.0, 2.5)
                else:
                    scale = random.uniform(0.1, 0.5)
                s.setScale(scale)
                
                # Add to spatial collision grid
                obs = SceneryObstacle(s.getPos(), radius=scale * 1.5)
                self.battle_system.scenery_grid.insert(obs)
        
        if tree_master:
            # Spread trees globally across the map
            for _ in range(600):
                x = random.uniform(-ground_half, ground_half)
                y = random.uniform(-ground_half, ground_half)
                
                # Removed center exclusion so trees populate the middle too!
                t = tree_master.copyTo(trees_parent)
                t.setPos(x, y, 0)
                t.setH(random.uniform(0, 360))
                scale = random.uniform(0.8, 1.6)
                t.setScale(scale)
                
                # Add to spatial collision grid (radius of tree trunk/base)
                obs = SceneryObstacle(t.getPos(), radius=scale * 1.6)
                self.battle_system.scenery_grid.insert(obs)

    # ------------------------------------------------------------------
    # Input + UI
    # ------------------------------------------------------------------
    def _setup_controls(self) -> None:
        # Mouse clicks to place units during player deployment.
        self.accept("mouse1", self._on_left_down)
        self.accept("mouse1-up", self._on_left_up)
        
        # Toggle spawn type
        self.accept("1", self._set_spawn_type, ["soldier"])
        self.accept("2", self._set_spawn_type, ["tank"])

        # Advance phase once the player is done placing.
        self.accept("enter", self._advance_phase)

        # Quit shortcut.
        self.accept("escape", self.userExit)

    def _setup_ui(self) -> None:
        try:
            # Use a bold, clean system font for a premium game look
            ui_font = self.loader.loadFont("/c/Windows/Fonts/ariblk.ttf")
        except Exception:
            ui_font = None

        font_kwargs = {"font": ui_font} if ui_font else {}

        self.status_text = OnscreenText(
            text="",
            pos=(-1.3, 0.82),  # Moved down slightly to clear the center phase text
            scale=0.045,
            fg=(0.95, 0.95, 0.95, 1.0),
            shadow=(0, 0, 0, 0.9),
            shadowOffset=(0.05, 0.05),
            align=TextNode.ALeft,
            mayChange=True,
            **font_kwargs
        )
        self.phase_text = OnscreenText(
            text="",
            pos=(0.0, 0.90),
            scale=0.07,
            fg=(1.0, 0.85, 0.1, 1.0),  # Golden yellow for phase headers
            shadow=(0, 0, 0, 1.0),
            shadowOffset=(0.06, 0.06),
            align=TextNode.ACenter,
            mayChange=True,
            **font_kwargs
        )
        self.result_text = OnscreenText(
            text="",
            pos=(0.0, 0.15),
            scale=0.09,
            fg=(0.2, 1.0, 0.3, 1.0),  # Bright green for results
            shadow=(0, 0, 0, 1.0),
            shadowOffset=(0.06, 0.06),
            align=TextNode.ACenter,
            mayChange=True,
            **font_kwargs
        )

    # ------------------------------------------------------------------
    # Mouse helpers
    # ------------------------------------------------------------------
    def _mouse_world_position(self) -> Optional[Point3]:
        """Project the current mouse position onto the ground plane (z=0).

        Uses base.camLens.extrude() and a CollisionRay-style ray to produce
        a world-space ray, then intersects that ray with the plane.
        """

        if not self.mouseWatcherNode.hasMouse():
            return None

        mpos = self.mouseWatcherNode.getMouse()
        near_point = Point3()
        far_point = Point3()

        # Convert 2D mouse position to a 3D line in camera space.
        self.camLens.extrude(mpos, near_point, far_point)

        # Transform into world space.
        near_world = self.render.getRelativePoint(self.camera, near_point)
        far_world = self.render.getRelativePoint(self.camera, far_point)

        # Build a ray similar to CollisionRay usage.
        ray_direction = (far_world - near_world).normalized()
        ray_origin = near_world

        # Intersect ray with the ground plane z=0.
        ground_plane = Plane(Vec3(0, 0, 1), Point3(0, 0, 0))
        hit_point = Point3()
        if not ground_plane.intersectsLine(hit_point, ray_origin, ray_origin + ray_direction * 1000.0):
            return None

        return hit_point

    def _position_in_player_zone(self, pos: Point3) -> bool:
        return (
            self.player_x_min <= pos.getX() <= self.player_x_max
            and self.y_min <= pos.getY() <= self.y_max
        )

    # ------------------------------------------------------------------
    # Placement input (Massive Drag to Spawn)
    # ------------------------------------------------------------------
    def _set_spawn_type(self, unit_type: str) -> None:
        self._current_spawn_type = unit_type

    def _on_left_down(self) -> None:
        if self.current_phase != GamePhase.BUY_AND_DEPLOY_PLAYER:
            return
        
        world_pos = self._mouse_world_position()
        if world_pos is None:
            return
        
        self._dragging = True
        self._drag_start_pos = Point3(world_pos.getX(), world_pos.getY(), 0.0)
        
        # Disable camera rotation while drawing spawn box
        self.camera_controller.enable_rotation = False

    def _on_left_up(self) -> None:
        if not self._dragging:
            return
        
        self._dragging = False
        self.camera_controller.enable_rotation = True
        
        if self._drag_rect_np is not None:
            node_np = self._drag_rect_np
            assert node_np is not None
            node_np.removeNode()
            self._drag_rect_np = None
            
        end_pos = self._mouse_world_position()
        if end_pos is None or self._drag_start_pos is None:
            return
        
        assert end_pos is not None
        end_pos.setZ(0.0)
        self._spawn_formation(self._drag_start_pos, end_pos, self._current_spawn_type)

    def _update_drag_visual(self) -> None:
        if not self._dragging or self._drag_start_pos is None:
            return
        
        end_pos = self._mouse_world_position()
        if end_pos is None:
            return
        
        if self._drag_rect_np is not None:
            node_np = self._drag_rect_np
            assert node_np is not None
            node_np.removeNode()

        ls = LineSegs()
        ls.setColor(0, 1, 0, 1)
        ls.setThickness(2.0)
        
        assert self._drag_start_pos is not None
        assert end_pos is not None
        x1, y1 = self._drag_start_pos.getX(), self._drag_start_pos.getY()
        x2, y2 = end_pos.getX(), end_pos.getY()
        
        ls.drawTo(x1, y1, 5.0)
        ls.drawTo(x2, y1, 5.0)
        ls.drawTo(x2, y2, 5.0)
        ls.drawTo(x1, y2, 5.0)
        ls.drawTo(x1, y1, 5.0)
        
        node = ls.create()
        self._drag_rect_np = self.render.attachNewNode(node)

    def _spawn_formation(self, start: Point3, end: Point3, unit_type: str) -> None:
        x_min = min(start.getX(), end.getX())
        x_max = max(start.getX(), end.getX())
        y_min = min(start.getY(), end.getY())
        y_max = max(start.getY(), end.getY())
        
        # Ensure minimum size to spawn at least one
        width = max(1.0, x_max - x_min)
        height = max(1.0, y_max - y_min)
        
        if unit_type == "soldier":
            cost = Soldier.DEFAULT_STATS.cost
            spacing = 1.2
        else:
            cost = Tank.DEFAULT_STATS.cost
            spacing = 3.0
            
        cols = max(1, int(width / spacing))
        rows = max(1, int(height / spacing))
        
        # Spawn unit by unit in formation
        for r in range(rows):
            for c in range(cols):
                if self.points_remaining < cost:
                    return
                
                x = x_min + c * spacing + (spacing * 0.5)
                y = y_min + r * spacing + (spacing * 0.5)
                
                pos = Point3(x, y, 0.5)
                
                if unit_type == "soldier":
                    unit = Soldier("player", pos, self.loader, self.render)
                else:
                    unit = Tank("player", pos, self.loader, self.render)
                    
                # Small random jitter so formations aren't perfectly robotic
                pos.setX(pos.getX() + random.uniform(-0.1, 0.1))
                pos.setY(pos.getY() + random.uniform(-0.1, 0.1))
                unit.node.setPos(pos)
                
                # Face AI territory
                unit.node.setH(90)

                self.player_army.add_unit(unit)
                self.points_remaining -= cost

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------
    def _advance_phase(self) -> None:
        if self.current_phase == GamePhase.BUY_AND_DEPLOY_PLAYER:
            self._start_ai_deployment()
        elif self.current_phase == GamePhase.RESULT:
            self._start_new_round()

    def _start_ai_deployment(self) -> None:
        """Ask the AITrainer for an army composition and spawn it."""

        player_spent = self.starting_points - self.points_remaining
        # If player placed nothing, give AI a tiny budget to prevent crashes
        ai_budget = max(10, player_spent)

        state = self.ai_trainer.build_state(self.player_army, self.ai_army, None)
        action = self.ai_trainer.select_action(state)
        # Give the AI exactly the same budget the player used, instead of the 50k max
        plan = self.ai_trainer.choose_composition(ai_budget, action)

        soldiers = plan["soldiers"]
        tanks = plan["tanks"]
        style = plan["style"]

        # Record for learning.
        self._ai_round_state = state
        self._ai_round_action = action

        # Choose spawn bands based on style.
        if style == "rush":
            x_min, x_max = self.ai_x_min, (self.ai_x_min + self.ai_x_max) * 0.5
        elif style == "defend":
            x_min, x_max = (self.ai_x_min + self.ai_x_max) * 0.5, self.ai_x_max
        else:
            x_min, x_max = self.ai_x_min, self.ai_x_max

        if style == "spread":
            y_min, y_max = self.y_min, self.y_max
        else:
            y_min, y_max = -40.0, 40.0

        for _ in range(soldiers):
            spawn_pos = random_position_in_range(x_min, x_max, y_min, y_max, z=0.5)
            unit = Soldier("ai", spawn_pos, self.loader, self.render)
            self.ai_army.add_unit(unit)

        for _ in range(tanks):
            spawn_pos = random_position_in_range(x_min, x_max, y_min, y_max, z=0.5)
            unit = Tank("ai", spawn_pos, self.loader, self.render)
            self.ai_army.add_unit(unit)

        # Any unspent points are left unused this round.
        self.current_phase = GamePhase.DEPLOY_AI

        # Immediately transition into battle.
        self._start_battle()

    def _start_battle(self) -> None:
        self.battle_timer = 0.0
        self.battle_system.start_battle()
        self.current_phase = GamePhase.BATTLE

    def _start_new_round(self) -> None:
        # Clear scene units
        for unit in self.player_army.units:
            if unit.alive:
                unit.cleanup()
        for unit in self.ai_army.units:
            if unit.alive:
                unit.cleanup()

        self.player_army.units.clear()
        self.ai_army.units.clear()

        self.points_remaining = self.starting_points
        self.current_phase = GamePhase.BUY_AND_DEPLOY_PLAYER
        self.result_text.setText("")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _update_task(self, task):
        from panda3d.core import ClockObject
        dt = ClockObject.getGlobalClock().getDt()

        # Camera controls are always available in every phase.
        if not self._dragging:
            self.camera_controller.enable_rotation = True
        self.camera_controller.update(dt)
        
        if self._dragging:
            self._update_drag_visual()

        if self.current_phase == GamePhase.BATTLE:
            self._update_battle(dt)

        self._update_ui()

        return task.cont

    def _update_battle(self, dt: float) -> None:
        self.battle_timer += dt
        result = self.battle_system.update(dt)

        if result in ("player", "ai", "draw"):
            self.current_phase = GamePhase.RESULT

            stats = self.battle_system.get_battle_stats()
            
            if result == "player":
                msg = "Player Wins!"
                reward = -100.0
            elif result == "ai":
                msg = "AI Wins!"
                reward = 100.0
            else:
                msg = "Draw!"
                reward = 0.0

            # Consider casualties in reward. AI wants to kill player troops efficiently.
            casualty_diff = stats.get("player_killed", 0) - stats.get("ai_killed", 0)
            reward += casualty_diff * 0.1

            # Provide the next state to the AI Trainer to finish the Q-learning episode
            next_state = self.ai_trainer.build_state(self.player_army, self.ai_army, self.battle_system)
            self.ai_trainer.finish_episode(reward, next_state)

            final_msg = f"{msg}\nPress ENTER for next round"
            if self._ai_round_action:
                final_msg += f"\n\nAI Strategy: {self._ai_round_action}"
                
            self.result_text.setText(final_msg)

    # ------------------------------------------------------------------
    # UI update
    # ------------------------------------------------------------------
    def _update_ui(self) -> None:
        player_units = self.player_army.count()
        ai_units = self.ai_army.count()

        if self.current_phase == GamePhase.BATTLE:
            phase_label = "Battle"
        elif self.current_phase == GamePhase.BUY_AND_DEPLOY_PLAYER:
            phase_label = "Player Deployment"
        elif self.current_phase == GamePhase.DEPLOY_AI:
            phase_label = "AI Deployment"
        else:
            phase_label = "Result"

        self.phase_text.setText(phase_label)

        timer_str = f"{self.battle_timer:5.1f}s" if self.current_phase == GamePhase.BATTLE else "--"

        self.status_text.setText(
            f"Budget: {self.points_remaining} pts\n"
            f"Player: {player_units} troops  |  AI: {ai_units} troops\n"
            f"Battle Time: {timer_str}\n"
            f"Equipped: [1] Soldier / [2] Tank  |  Active: {self._current_spawn_type.upper()}\n"
            "Action: Drag to deploy formation. Press ENTER to end turn."
        )



if __name__ == "__main__":
    game = GameManager()
    game.run()
