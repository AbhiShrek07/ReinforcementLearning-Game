from __future__ import annotations

from typing import Literal, Optional

from panda3d.core import Vec3

from units import PlayerArmy, AIArmy, Unit, SpatialGrid


BattleResult = Literal["player", "ai", "draw", "in_progress"]


class BattleSystem:
    """Coordinates movement, combat, and victory conditions between two armies."""

    def __init__(self, player_army: PlayerArmy, ai_army: AIArmy, max_battle_time: float = 300.0) -> None:
        self.player_army = player_army
        self.ai_army = ai_army

        self.max_battle_time = max_battle_time
        self.time_elapsed: float = 0.0
        self._finished: bool = False
        self._winner: Optional[BattleResult] = None

        self._player_initial_units: int = 0
        self._ai_initial_units: int = 0
        
        self.player_grid = SpatialGrid(cell_size=20.0)
        self.ai_grid = SpatialGrid(cell_size=20.0)
        self.scenery_grid = SpatialGrid(cell_size=20.0)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start_battle(self) -> None:
        self.time_elapsed = 0.0
        self._finished = False
        self._winner = None

        self._player_initial_units = len(self.player_army.units)
        self._ai_initial_units = len(self.ai_army.units)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, dt: float) -> BattleResult:
        """Advance the battle simulation by one frame."""

        if self._finished:
            return self._winner or "in_progress"

        self.time_elapsed += dt

        player_enemies = self.ai_army.living_units()
        ai_enemies = self.player_army.living_units()

        # Update spatial grid for fast targeting lookups
        self.player_grid.clear()
        self.ai_grid.clear()
        
        # Insert units into their respective grids
        for unit in ai_enemies:  # Player units (ai_enemies)
            self.player_grid.insert(unit)
        for unit in player_enemies:  # AI units (player_enemies)
            self.ai_grid.insert(unit)

        # Player units think and act (searching AI grid and avoiding scenery)
        for unit in self.player_army.living_units():
            unit.update(dt, player_enemies, enemy_grid=self.ai_grid, my_grid=self.player_grid, scenery_grid=self.scenery_grid)

        # AI units think and act (searching Player grid and avoiding scenery)
        for unit in self.ai_army.living_units():
            unit.update(dt, ai_enemies, enemy_grid=self.player_grid, my_grid=self.ai_grid, scenery_grid=self.scenery_grid)

        # Remove any dead units from the army lists.
        self.player_army.cleanup_dead()
        self.ai_army.cleanup_dead()

        # Victory conditions.
        if not self.player_army.living_units() and not self.ai_army.living_units():
            self._set_result("draw")
        elif not self.player_army.living_units():
            self._set_result("ai")
        elif not self.ai_army.living_units():
            self._set_result("player")
        elif self.time_elapsed >= self.max_battle_time:
            # Sudden death on time-out.
            player_count = self.player_army.count()
            ai_count = self.ai_army.count()
            if player_count > ai_count:
                self._set_result("player")
            elif ai_count > player_count:
                self._set_result("ai")
            else:
                self._set_result("draw")

        return self._winner or "in_progress"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_result(self, result: BattleResult) -> None:
        self._finished = True
        self._winner = result

    def is_finished(self) -> bool:
        return self._finished

    def winner(self) -> BattleResult:
        return self._winner or "in_progress"

    def get_battle_stats(self) -> dict:
        """Return a snapshot of the current battle state for UI / AI."""

        player_alive = self.player_army.count()
        ai_alive = self.ai_army.count()

        player_killed = max(0, self._player_initial_units - player_alive)
        ai_killed = max(0, self._ai_initial_units - ai_alive)

        return {
            "time": self.time_elapsed,
            "player_alive": player_alive,
            "ai_alive": ai_alive,
            "player_killed": player_killed,
            "ai_killed": ai_killed,
        }

    def get_map_control(self) -> float:
        """Rough measure of which side controls more of the map.

        Returns a value in [-1, 1] where:
        -1 -> AI is fully pushed into player territory,
         0 -> front line is roughly in the middle,
         1 -> player is deep into AI territory.
        """

        player_x = self.player_army.average_x()
        ai_x = self.ai_army.average_x()
        if self.player_army.count() == 0 and self.ai_army.count() == 0:
            return 0.0

        # Avoid division by zero: normalize difference by a nominal half-width.
        diff = player_x - ai_x
        nominal_half_width = 100.0
        return max(-1.0, min(1.0, diff / nominal_half_width))

