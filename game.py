"""Entry point that runs the large-scale 3D war simulation.

This file is kept tiny on purpose; the actual game logic lives in:

- main.py            -> GameManager (Panda3D application)
- units.py           -> Unit, Soldier, Tank, PlayerArmy, AIArmy
- battle_system.py   -> BattleSystem (combat and victory)
- ai_learning.py     -> AITrainer (Q-learning + ai_memory.json)
- camera_controller.py -> CameraController (RTS camera)

Run the game with either:

    python game.py
or
    python main.py
"""

from main import GameManager


if __name__ == "__main__":
    game = GameManager()
    game.run()

