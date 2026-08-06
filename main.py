from agent.agent import agent
from kaggle_environments import make

env = make("kaggriculture", debug=True)
print(f"Environment: {env.name} v{env.version}")
print(f"Players: {env.specification.agents}")
print(f"Max steps: {env.configuration.episodeSteps}")

env = make("kaggriculture", debug=True)
env.run([agent, "random"])

final = env.steps[-1]
for i, s in enumerate(final):
    print(f"Player {i}: reward={s.reward}, status={s.status}")