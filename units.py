from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from panda3d.core import Vec3, Point3, NodePath
from direct.actor.Actor import Actor


class SceneryObstacle:
    """Mock unit to represent trees and stones in the spatial grid."""
    def __init__(self, pos: Point3, radius: float):
        self.node = NodePath("scenery_obs")
        self.node.setPos(pos)
        self.alive = True
        self.radius = radius


class SpatialGrid:
    """A 2D spatial partition grid to optimize nearest-neighbor searches."""

    def __init__(self, cell_size: float) -> None:
        self.cell_size = cell_size
        self.cells: Dict[Tuple[int, int], List["Unit"]] = {}

    def clear(self) -> None:
        self.cells.clear()

    def _get_cell_coord(self, pos: Point3) -> Tuple[int, int]:
        return (
            int(pos.getX() // self.cell_size),
            int(pos.getY() // self.cell_size),
        )

    def insert(self, unit: "Unit") -> None:
        if not unit.alive:
            return
        coord = self._get_cell_coord(unit.node.getPos())
        if coord not in self.cells:
            self.cells[coord] = []
        self.cells[coord].append(unit)

    def get_nearby_units(self, pos: Point3, radius: float) -> List["Unit"]:
        """Return all units in cells touched by the given radius."""
        min_coord = self._get_cell_coord(Point3(pos.getX() - radius, pos.getY() - radius, 0))
        max_coord = self._get_cell_coord(Point3(pos.getX() + radius, pos.getY() + radius, 0))

        nearby = []
        for cx in range(min_coord[0], max_coord[0] + 1):
            for cy in range(min_coord[1], max_coord[1] + 1):
                if (cx, cy) in self.cells:
                    nearby.extend(self.cells[(cx, cy)])
        return nearby


@dataclass
class UnitStats:
    """Configuration container for a unit type."""

    health: float
    damage: float
    speed: float
    attack_range: float
    cost: int
    scale: float
    model_path: str


class Unit:
    """Base combat unit with simple movement and combat behaviour."""

    def __init__(
        self,
        name: str,
        team: str,
        position: Point3,
        stats: UnitStats,
        model_loader,
        parent_node,
    ) -> None:
        self.name = name
        self.team = team
        self.stats = stats

        self.max_health: float = stats.health
        self.health: float = stats.health
        self.damage: float = stats.damage
        self.speed: float = stats.speed
        self.attack_range: float = stats.attack_range
        self.cost: int = stats.cost

        # Root node for this unit; the visual model is parented under it.
        self.node = parent_node.attachNewNode(name)

        # Load model using Actor to support skeletons/rigged meshes properly.
        # For our specific static GLB models, we bypass Actor directly to prevent cache bugs across rounds.
        if not hasattr(Unit, "_custom_model_cache"):
            Unit._custom_model_cache = {}

        if "desert_storm" in stats.model_path or "panzer" in stats.model_path:
            # We use an isolated custom cache to completely avoid Panda3D's internal ModelPool / Actor bugs.
            if stats.model_path not in Unit._custom_model_cache:
                fresh_model = model_loader.loadModel(stats.model_path, noCache=True)
                # Prepare it once cleanly
                for np in fresh_model.findAllMatches("**/+GeomNode"):
                    np.clearTransform()
                fresh_model.flattenLight()
                Unit._custom_model_cache[stats.model_path] = fresh_model
            
            master_model = Unit._custom_model_cache[stats.model_path]
            model_np = master_model.copyTo(self.node)
        else:
            try:
                model_np = Actor(stats.model_path)
                b = model_np.getBounds()
                if b.isEmpty() or math.isnan(b.getCenter().getX()):
                    raise ValueError("Corrupted bounds in Actor")
                if model_np.getAnimNames():
                    model_np.pose(model_np.getAnimNames()[0], 0)
            except Exception:
                if stats.model_path not in Unit._custom_model_cache:
                    fresh_model = model_loader.loadModel(stats.model_path, noCache=True)
                    for np in fresh_model.findAllMatches("**/+GeomNode"):
                        np.clearTransform()
                    fresh_model.flattenLight()
                    Unit._custom_model_cache[stats.model_path] = fresh_model
                    
                master_model = Unit._custom_model_cache[stats.model_path]
                model_np = master_model.copyTo(self.node)
            
        self.model_np = model_np
        self.model_np.reparentTo(self.node)
        self.model_np.setScale(stats.scale)
        if isinstance(self, Soldier):
            self.model_np.setP(90)
        elif isinstance(self, Tank):
            self.model_np.setP(90)
        
        # Apply team colors (Brightened significantly for visible contrast against the new ground)
        if self.team == "player":
            # Bright sky-blue tint
            model_np.setColorScale(0.3, 0.7, 1.0, 1.0)
        else:
            # Bright crimson/orange tint
            model_np.setColorScale(1.0, 0.25, 0.2, 1.0)

        # Position the unit on the ground plane
        self.node.setPos(position.x, position.y, 0.0)

        # Combat state
        self.alive: bool = True
        self._target: Optional["Unit"] = None
        self._target_refresh_interval: float = 0.4  # base seconds
        # Jitter the starting timer across 2 seconds so 50,000 units don't all
        # search the spatial grid simultaneously on frame 1, causing a massive hang.
        self._target_refresh_timer: float = random.uniform(0.0, 2.0)

    def cleanup(self) -> None:
        """Safely destroy this unit's visuals without corrupting the global Actor geometry cache."""
        self.alive = False
        self.model_np.removeNode()
        self.node.removeNode()

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------
    def distance_to(self, other: "Unit") -> float:
        return (self.node.getPos() - other.node.getPos()).length()

    def _nearest_enemy(self, enemies: List["Unit"], spatial_grid: Optional[SpatialGrid] = None) -> Optional["Unit"]:
        nearest: Optional["Unit"] = None
        best_dist_sq = float("inf")
        my_pos = self.node.getPos()

        # If we have a spatial grid, only search within a reasonable combat radius
        # (e.g., 20 units away). If none found, we fall back to a global search,
        # but in massive battles, they usually find someone close immediately.
        # Keeping radius small saves millions of distance checks.
        if spatial_grid is not None:
            # Progressively expand search radius to find at least one enemy without freezing
            # the game comparing against 30,000 units on the other side of the massive map.
            for radius in (20.0, 100.0, 1000.0):
                search_pool = spatial_grid.get_nearby_units(my_pos, radius=radius)
                if search_pool:
                    break
            
            if not search_pool:
                search_pool = enemies  # Fallback if totally isolated
        else:
            search_pool = enemies

        for e in search_pool:
            if not e.alive or e.team == self.team:
                continue
            d_sq = (e.node.getPos() - my_pos).lengthSquared()
            if d_sq < best_dist_sq:
                best_dist_sq = d_sq
                nearest = e

        return nearest

    # ------------------------------------------------------------------
    # Per-frame logic
    # ------------------------------------------------------------------
    def update(self, dt: float, enemies: List["Unit"], enemy_grid: Optional[SpatialGrid] = None, my_grid: Optional[SpatialGrid] = None, scenery_grid: Optional[SpatialGrid] = None) -> None:
        """Update this unit: acquire targets, move, and attack."""

        if not self.alive:
            return

        # Acquire a target periodically to avoid heavy per-frame searches.
        if enemies:
            self._target_refresh_timer -= dt
            if self._target is None or (not self._target.alive) or self._target_refresh_timer <= 0.0:
                self._target = self._nearest_enemy(enemies, enemy_grid)
                # Re-jitter slightly to prevent unit timings from syncing back up
                self._target_refresh_timer = self._target_refresh_interval + random.uniform(-0.1, 0.1)

        if self._target is not None and self._target.alive:
            self._move_and_attack(dt, self._target, my_grid, enemy_grid, scenery_grid)
        else:
            # Mild idle rotation so units do not look static.
            self.node.setH(self.node.getH() + 10.0 * dt)

        if self.health <= 0.0 and self.alive:
            self.cleanup()

    def _move_and_attack(self, dt: float, target: "Unit", my_grid: Optional[SpatialGrid], enemy_grid: Optional[SpatialGrid], scenery_grid: Optional[SpatialGrid]) -> None:
        my_pos = self.node.getPos()
        target_pos = target.node.getPos()

        # 1. Base directional pull towards the enemy
        offset = target_pos - my_pos
        offset.setZ(0.0)  # keep units on ground plane

        dist = offset.length()
        
        move_vec = Vec3(0, 0, 0)
        heading = self.node.getH()

        # 2. Separation/Avoidance from nearby units to prevent dense overlapping
        # We cap the number of units checked to maintain performance.
        separation_radius = 2.0
        separation_push = Vec3(0, 0, 0)
        neighbors_checked = 0
        MAX_NEIGHBORS = 15  # Limit checks for performance
        
        # Check allies
        if my_grid:
            allies = my_grid.get_nearby_units(my_pos, separation_radius)
            for ally in allies:
                if ally is self or not ally.alive:
                    continue
                neighbors_checked += 1
                if neighbors_checked > MAX_NEIGHBORS: break
                
                diff = my_pos - ally.node.getPos()
                diff.setZ(0)
                d = diff.lengthSquared()
                if 0.001 < d < separation_radius * separation_radius:
                    diff.normalize()
                    # Stronger push the closer they are
                    separation_push += diff * (separation_radius - math.sqrt(d)) * 2.0
                    
        # Check enemies for separation (prevent clipping through enemies)
        if enemy_grid and neighbors_checked <= MAX_NEIGHBORS:
            enemies_near = enemy_grid.get_nearby_units(my_pos, separation_radius)
            for e in enemies_near:
                if not e.alive: continue
                neighbors_checked += 1
                if neighbors_checked > MAX_NEIGHBORS: break
                
                diff = my_pos - e.node.getPos()
                diff.setZ(0)
                d = diff.lengthSquared()
                # Use slightly larger separation from enemies to maintain combat spacing
                if 0.001 < d < (separation_radius * 1.2) ** 2:
                    diff.normalize()
                    separation_push += diff * (separation_radius * 1.2 - math.sqrt(d)) * 3.0

        # Check scenery to completely avoid walking through trees and rocks
        if scenery_grid:
            # Trees and rocks can be larger, so we check a slightly wider radius
            scenery_near = scenery_grid.get_nearby_units(my_pos, 6.0)
            for s in scenery_near:
                diff = my_pos - s.node.getPos()
                diff.setZ(0)
                d = diff.lengthSquared()
                obs_radius = s.radius + 0.8 # Padding to account for unit body
                if 0.001 < d < obs_radius ** 2:
                    diff.normalize()
                    # Very strong push so units slide off trees quickly instead of clipping
                    separation_push += diff * (obs_radius - math.sqrt(d)) * 12.0

        if dist > 1e-3:
            # Rotate smoothly toward target (RTS style yaw only).
            heading = math.degrees(math.atan2(offset.getX(), offset.getY()))
            self.node.setH(heading)

        if dist > self.attack_range:
            # Move toward target
            offset.normalize()
            base_move = offset * self.speed
            
            # Combine base movement with separation force
            final_velocity = base_move + separation_push * 5.0
            move_vec = final_velocity * dt
            
            self.node.setPos(my_pos + move_vec)
        else:
            # Even if in range and not moving forward, still apply separation so they shift out of overlapping
            if separation_push.lengthSquared() > 0.1:
                final_velocity = separation_push * 5.0
                move_vec = final_velocity * dt
                self.node.setPos(my_pos + move_vec)
            
            # In range: apply continuous damage over time.
            target.health -= self.damage * dt


class Soldier(Unit):
    """Fast, cheap infantry unit."""

    DEFAULT_STATS = UnitStats(
        health=100.0,
        damage=10.0,
        speed=8.0,
        attack_range=3.0,
        cost=1,
        # Scaled up per user request so they aren't tiny compared to trees
        scale=0.7,
        model_path="models/desert_storm_game_all_characters_3d_models.glb",
    )

    def __init__(self, team: str, position: Point3, model_loader, parent_node) -> None:
        super().__init__("Soldier", team, position, Soldier.DEFAULT_STATS, model_loader, parent_node)


class Tank(Unit):
    """Heavy, slow armored unit."""

    DEFAULT_STATS = UnitStats(
        health=500.0,
        damage=40.0,
        speed=3.0,
        attack_range=4.0,
        cost=10,
        # Increased scale to match environment tweaks
        scale=2.2,
        model_path="models/panzer_ii_luchs.glb",
    )

    def __init__(self, team: str, position: Point3, model_loader, parent_node) -> None:
        super().__init__("Tank", team, position, Tank.DEFAULT_STATS, model_loader, parent_node)


class Army:
    """Shared logic for both armies."""

    def __init__(self, name: str, side: str) -> None:
        self.name = name
        self.side = side  # "player" or "ai"
        self.units: List[Unit] = []

    def add_unit(self, unit: Unit) -> None:
        self.units.append(unit)

    def living_units(self) -> List[Unit]:
        return [u for u in self.units if u.alive]

    def cleanup_dead(self) -> None:
        self.units = [u for u in self.units if u.alive]

    def count(self) -> int:
        return len(self.living_units())

    def average_x(self) -> float:
        living = self.living_units()
        if not living:
            return 0.0
        return sum(u.node.getX() for u in living) / float(len(living))


class PlayerArmy(Army):
    def __init__(self) -> None:
        super().__init__("Player Army", "player")


class AIArmy(Army):
    def __init__(self) -> None:
        super().__init__("AI Army", "ai")


def random_position_in_range(
    x_min: float, x_max: float, y_min: float, y_max: float, z: float = 0.0
) -> Point3:
    """Utility used by both armies to spawn units inside a rectangle."""

    return Point3(
        random.uniform(x_min, x_max),
        random.uniform(y_min, y_max),
        z,
    )

