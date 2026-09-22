from __future__ import annotations

import json
import os
import random
from typing import Dict, List, Tuple

from battle_system import BattleSystem
from units import PlayerArmy, AIArmy


Action = str
State = Tuple[int, int, int, int]


class AITrainer:
    """Simple tabular Q-learning for AI army composition and tactical style."""

    # High-level strategy choices for the AI.
    ACTIONS: List[Action] = [
        "spawn_more_soldiers",
        "spawn_more_tanks",
        "balanced_army",
        "rush_attack",
        "defend",
        "spread_units",
    ]

    def __init__(
        self,
        memory_path: str | None = None,
        alpha: float = 0.5,
        gamma: float = 0.0,
        epsilon: float = 0.2,
    ) -> None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.memory_path = memory_path or os.path.join(base_dir, "ai_memory.json")

        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon

        self.q_table: Dict[str, Dict[Action, float]] = {}
        self._last_state: State | None = None
        self._last_action: Action | None = None

        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.memory_path):
            self.q_table = {}
            return

        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                self.q_table = json.load(f)
        except Exception:
            # Corrupt or incompatible file – start fresh.
            self.q_table = {}

    def _save(self) -> None:
        try:
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump(self.q_table, f, indent=2)
        except Exception:
            # Failing to save should not crash the game.
            pass

    # ------------------------------------------------------------------
    # State encoding
    # ------------------------------------------------------------------
    def build_state(
        self,
        player_army: PlayerArmy,
        ai_army: AIArmy,
        battle_system: BattleSystem | None = None,
    ) -> State:
        """Convert current game situation into a small discrete state."""

        player_soldiers = sum(1 for u in player_army.units if u.name == "Soldier")
        player_tanks = sum(1 for u in player_army.units if u.name == "Tank")

        ai_soldiers = sum(1 for u in ai_army.units if u.name == "Soldier")
        ai_tanks = sum(1 for u in ai_army.units if u.name == "Tank")

        # Relative troop strength ratios, bucketized.
        # Scaled up for 50,000 point budgets (massive armies)
        strength_ratio = (ai_soldiers + 2 * ai_tanks) - (player_soldiers + 2 * player_tanks)

        if strength_ratio < -2000:
            strength_bucket = 0
        elif strength_ratio < -500:
            strength_bucket = 1
        elif strength_ratio < 500:
            strength_bucket = 2
        elif strength_ratio < 2000:
            strength_bucket = 3
        else:
            strength_bucket = 4

        # Player tank density: is the player relying mostly on tanks?
        total_player = max(1, player_soldiers + player_tanks)
        tank_ratio = player_tanks / float(total_player)
        if tank_ratio < 0.1:
            tank_bucket = 0
        elif tank_ratio < 0.3:
            tank_bucket = 1
        elif tank_ratio < 0.6:
            tank_bucket = 2
        elif tank_ratio < 0.9:
            tank_bucket = 3
        else:
            tank_bucket = 4

        # Map control – derived from the front line position.
        if battle_system is not None:
            mc_value = battle_system.get_map_control()
        else:
            mc_value = 0.0

        if mc_value < -0.5:
            map_control_bucket = 0  # AI pushed back
        elif mc_value < -0.1:
            map_control_bucket = 1
        elif mc_value < 0.1:
            map_control_bucket = 2
        elif mc_value < 0.5:
            map_control_bucket = 3
        else:
            map_control_bucket = 4

        # Average X distance between armies (coarse bucket).
        distance_bucket = 2  # neutral before combat starts

        return (
            strength_bucket,
            tank_bucket,
            map_control_bucket,
            distance_bucket,
        )

    def _state_key(self, state: State) -> str:
        return ",".join(str(v) for v in state)

    # ------------------------------------------------------------------
    # Action selection
    # ------------------------------------------------------------------
    def select_action(self, state: State) -> Action:
        """Epsilon-greedy choice of a high-level strategy."""

        if random.random() < self.epsilon:
            action = random.choice(self.ACTIONS)
        else:
            key = self._state_key(state)
            q_values = self.q_table.get(key, {})
            if not q_values:
                action = random.choice(self.ACTIONS)
            else:
                # Greedy over learnt Q-values.
                action = max(q_values, key=lambda k: q_values[k])

        self._last_state = state
        self._last_action = action
        return action

    # ------------------------------------------------------------------
    # Q-learning update
    # ------------------------------------------------------------------
    def finish_episode(self, reward: float, next_state: State | None = None) -> None:
        """Update the Q-table after a round finishes."""

        assert self._last_state is not None
        assert self._last_action is not None

        last_action: str = self._last_action
        s_key = self._state_key(self._last_state)
        q_for_state = self.q_table.setdefault(s_key, {a: 0.0 for a in self.ACTIONS})

        old_q = q_for_state[last_action]

        if next_state is not None:
            assert next_state is not None
            next_key = self._state_key(next_state)
            next_q_values = self.q_table.get(next_key, {a: 0.0 for a in self.ACTIONS})
            max_next_q = max(next_q_values.values()) if next_q_values else 0.0
        else:
            max_next_q = 0.0

        updated_q = old_q + self.alpha * (reward + self.gamma * max_next_q - old_q)
        q_for_state[last_action] = updated_q

        self._save()

    # ------------------------------------------------------------------
    # Decoding actions into composition / tactics
    # ------------------------------------------------------------------
    def choose_composition(self, total_points: int, action: Action) -> dict:
        """Translate a high-level action into concrete unit counts and formation style."""

        # Simple rules-of-thumb for how each action spends the budget.
        if action == "spawn_more_soldiers":
            soldiers_budget_ratio = 0.9
        elif action == "spawn_more_tanks":
            soldiers_budget_ratio = 0.2
        elif action == "balanced_army":
            soldiers_budget_ratio = 0.5
        else:
            soldiers_budget_ratio = 0.6

        # Costs derived from unit defaults (mirrors Unit definitions).
        soldier_cost = 1
        tank_cost = 10

        soldier_points = int(total_points * soldiers_budget_ratio)
        tank_points = total_points - soldier_points

        num_soldiers = soldier_points // soldier_cost
        num_tanks = tank_points // tank_cost

        # Ensure at least one unit if we have any budget at all.
        if num_soldiers == 0 and num_tanks == 0 and total_points >= soldier_cost:
            num_soldiers = total_points // soldier_cost

        # Tactical style influences spawn shape (handled by GameManager).
        if action == "rush_attack":
            style = "rush"
        elif action == "defend":
            style = "defend"
        elif action == "spread_units":
            style = "spread"
        else:
            style = "standard"

        return {
            "soldiers": num_soldiers,
            "tanks": num_tanks,
            "style": style,
        }

