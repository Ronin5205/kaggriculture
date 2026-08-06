"""
Kaggriculture Kaggle submission entrypoint.

Kaggle loads this file via exec and uses the **last top-level callable** as the
agent. Keep `agent` as that last callable — do not define other functions or
import other callables (e.g. `make`) at module scope after it.

The loader adds this file's directory to sys.path during exec, so the sibling
`agent/` package imports cleanly.

Submit the multi-file bundle (from repo root):

    tar -czf submission.tar.gz main.py agent
    kaggle competitions submit kaggriculture -f submission.tar.gz -m "goose egg engine"
"""

from agent.agent import agent  # must remain the last top-level callable


# Kaggle execs with a bare namespace (no __name__ / __file__). Guard so load
# succeeds; local `python main.py` still runs the harness.
if globals().get("__name__") == "__main__":
    from kaggle_environments import make

    env = make("kaggriculture", debug=True)
    print(f"Environment: {env.name} v{env.version}")
    print(f"Max steps: {env.configuration.episodeSteps}")
    env.run([agent, "starter"])
    for i, s in enumerate(env.steps[-1]):
        print(f"Player {i}: reward={s.reward}, status={s.status}")
