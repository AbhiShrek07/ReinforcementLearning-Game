# Reinforcement Learning Battle Simulator

A large-scale 3D real-time strategy game built with [Panda3D](https://www.panda3d.org/),
in which you draw out an army of thousands of units and watch it fight an opponent that
**learns from every round it plays against you**.

The opponent is not scripted. It is a tabular Q-learning agent that picks a strategy,
watches how the battle turns out, and updates its value estimates. Its experience is
written to `ai_memory.json`, so it carries what it has learned across sessions.

---

## Table of contents

- [How the game plays](#how-the-game-plays)
- [Units](#units)
- [Controls](#controls)
- [The learning AI](#the-learning-ai)
- [Installation](#installation)
- [Running the game](#running-the-game)
- [Project layout](#project-layout)
- [Resetting or inspecting the AI's memory](#resetting-or-inspecting-the-ais-memory)
- [Known limitations](#known-limitations)

---

## How the game plays

Each round moves through four phases:

| Phase | What happens |
| --- | --- |
| **Buy & deploy** | You have **50,000 points**. Pick a unit type and drag a rectangle on your half of the map to fill it with a formation. Units are bought as they are placed, until the rectangle is full or you run out of points. |
| **AI deploys** | The AI is handed **exactly as many points as you actually spent**, then chooses a composition and a spawn shape from what it has learned. |
| **Battle** | Both armies fight autonomously. Every unit seeks its nearest enemy, closes to weapons range, and attacks. |
| **Result** | The winner is shown, the AI updates its Q-table, and `ENTER` starts a fresh round. |

The battlefield is 1000 x 1000 units. You deploy on the west side, the AI on the east,
with a no-man's-land between the two zones.

A battle ends when one army is wiped out, or after **300 seconds**, in which case the
side with more surviving units wins. Equal counts are a draw.

## Units

| Unit | Cost | Health | Damage/s | Speed | Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Soldier** | 1 | 100 | 10 | 8.0 | 3.0 |
| **Tank** | 10 | 500 | 40 | 3.0 | 4.0 |

A tank costs ten soldiers, has five times the health and four times the damage, so the
interesting question each round is whether mass or quality wins — and that is exactly the
trade-off the AI is learning about.

Targeting runs through a uniform [spatial grid](units.py) with 20-unit cells rather than
an all-pairs scan, which is what keeps battles of this size at a playable frame rate.

## Controls

**Deployment**

| Input | Action |
| --- | --- |
| `1` / `2` | Select soldiers / tanks |
| Left-drag | Draw a rectangle and fill it with a formation |
| `ENTER` | Finish deploying and start the battle |

**Camera** (always available)

| Input | Action |
| --- | --- |
| `W` `A` `S` `D` | Pan |
| `Q` / `E` | Raise / lower |
| `SHIFT` | Sprint (4x pan speed) |
| Mouse wheel | Zoom |
| Right-drag | Rotate and tilt |

**Other**

| Input | Action |
| --- | --- |
| `ENTER` (on the result screen) | Next round |
| `ESC` | Quit |

## The learning AI

The agent lives in [`ai_learning.py`](ai_learning.py) and is a straightforward tabular
Q-learner — no neural network, no framework, about 200 readable lines.

**Actions.** Each round it picks one of six high-level strategies, which are then
translated into a concrete build and spawn pattern:

| Action | Effect |
| --- | --- |
| `spawn_more_soldiers` | 90% of the budget on infantry |
| `spawn_more_tanks` | 80% of the budget on armour |
| `balanced_army` | An even split |
| `rush_attack` | Standard mix, deployed against the front of its zone |
| `defend` | Standard mix, deployed at the back of its zone |
| `spread_units` | Standard mix, spread across the full width of the map |

**State.** The situation is compressed into four discrete buckets, used as the Q-table key:

1. **Strength differential** — the AI's weighted unit count minus yours, in five bands
2. **Your tank ratio** — how heavily you are leaning on armour, in five bands
3. **Map control** — where the front line sat, derived from the average X of both armies
4. **Engagement distance** — reserved; see [Known limitations](#known-limitations)

**Reward.** After each battle: `+100` for a win, `-100` for a loss, `0` for a draw, plus
`0.1` per unit of casualty differential. A narrow win therefore scores lower than a
one-sided one, and a loss that still cost you dearly is penalised less.

**Update.** The standard Q-learning rule, with `alpha = 0.5`, `gamma = 0.0` and
`epsilon = 0.2` — meaning it explores a random strategy one round in five, and otherwise
plays the best it knows. The table is flushed to `ai_memory.json` after every round.

```
Q(s,a) <- Q(s,a) + alpha * (r + gamma * max Q(s',a') - Q(s,a))
```

Because the repository ships with a populated `ai_memory.json`, the AI starts out with
prior experience rather than from scratch.

## Installation

Requires **Python 3.9 or newer** (3.11 is what the bundled installer targets) and a GPU
capable of OpenGL.

**Windows — one step**

```bat
setup.bat
```

This checks for Python, installs it if it is missing, creates a virtual environment,
installs dependencies, and launches the game.

**Any platform — manual**

```bash
git clone https://github.com/AbhiShrek07/ReinforcementLearning-Game.git
cd ReinforcementLearning-Game

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

The only dependency is `panda3d==1.10.16`.

> **Note:** the repository includes roughly 95 MB of `.glb` models and textures under
> [`models/`](models/), so the initial clone is not small.

## Running the game

```bash
python game.py
```

`python main.py` does the same thing. [`game.py`](game.py) is only a thin entry point
around `GameManager`.

Start modestly — a few thousand soldiers — and scale up once you know how your machine
handles the unit count.

## Project layout

| File | Responsibility |
| --- | --- |
| [`game.py`](game.py) | Entry point |
| [`main.py`](main.py) | `GameManager` — phases, input, terrain, HUD, reward calculation |
| [`units.py`](units.py) | `Unit`, `Soldier`, `Tank`, the army containers, and the spatial grid |
| [`battle_system.py`](battle_system.py) | Per-frame combat resolution, victory conditions, battle stats |
| [`ai_learning.py`](ai_learning.py) | `AITrainer` — Q-learning, state encoding, action decoding |
| [`camera_controller.py`](camera_controller.py) | RTS camera |
| `ai_memory.json` | The learned Q-table |
| [`models/`](models/) | Meshes and textures |

## Resetting or inspecting the AI's memory

`ai_memory.json` is plain JSON, keyed by the comma-joined state bucket, with one Q-value
per action:

```json
{
  "1,1,2,2": {
    "spawn_more_soldiers": 0.0,
    "spawn_more_tanks": 2.0,
    "balanced_army": 0.0,
    "rush_attack": 0.0,
    "defend": 0.0,
    "spread_units": 0.0
  }
}
```

Delete the file to make the AI start over with no experience; it is recreated after the
next completed round. Keeping a copy before a long session is an easy way to compare what
it converges on against different play styles.

## Known limitations

These are deliberate simplifications, listed here so nobody has to rediscover them by
reading the source:

- **`gamma` is `0.0`** and each round is scored as a single-step episode, so the agent is
  closer to a contextual bandit than to full temporal-difference learning: it optimises
  the current round rather than a sequence of them. Raising `gamma` in
  [`AITrainer.__init__`](ai_learning.py) is the obvious first experiment.
- **The fourth state dimension is a constant.** `build_state` always emits `2` for the
  engagement-distance bucket, so it currently carries no information. It is wired through
  and ready for a real measurement.
- **Exploration never decays.** `epsilon` is fixed at `0.2`, so the AI keeps spending one
  round in five on a random strategy even after it has learned a good policy.
- **Tactical style is not learned separately from composition.** A single action decides
  both, so the agent cannot combine, say, a tank-heavy build with a spread deployment.
