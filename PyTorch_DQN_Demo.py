'''
It is a very simple PyTorch demo for DQN algorithm on Atari game.
Here the game is "Breakout"
Enjoy!
Author: Guanya Shi
California Institute of Technology
gshi@caltech.edu
'''

'''
Some memos:
(1) Action space: 0, 1, 2, 3:
0: do nothing
1: start our game (the ball will appear)
2: move our bar to the right
3: move our bar to the left
(2) Observation space: 210 x 160 x 3 image
(3) We have 5 lives. Once one life is done, we need to take action 1 to restart the game.
(4) After each step, the env will feedback observation, reward, done and info:
observation: 210 x 160 x 3 image
reward: reward = x, where x is the number of blocks our ball hits in one step
done: True if the game is over (use up 5 lives)
info: number of lives left
(5) Three number on the top of the screen:
000 score
5 number of lives
1 game mode
'''

#########################################################
#########################################################
# Import packages
import gym
import math
import random
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from collections import namedtuple
from itertools import count
from PIL import Image

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torchvision.transforms as T

# if gpu is to be used
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

env = gym.make('Breakout-v0').unwrapped

# set up matplotlib
is_ipython = 'inline' in matplotlib.get_backend()
if is_ipython:
    from IPython import display

plt.ion()


#########################################################
#########################################################
# Replay Memory
Transition = namedtuple('Transition', ('state', 'action', 'next_state', 'reward'))

class ReplayMemory(object):

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        """Saves a transition."""
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


#########################################################
#########################################################
# Q-network
class DQN(nn.Module):

    def __init__(self):
        super(DQN, self).__init__()
        self.conv1 = nn.Conv2d(1, 8, kernel_size=4, stride=2)
        self.bn1 = nn.BatchNorm2d(8)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(8, 16, kernel_size=4, stride=2)
        self.bn2 = nn.BatchNorm2d(16)
        self.conv3 = nn.Conv2d(16, 16, kernel_size=4, stride=2)
        self.bn3 = nn.BatchNorm2d(16)
        self.head = nn.Linear(144, 2)

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.pool(x)
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.relu(self.bn3(self.conv3(x)))
        return self.head(x.view(x.size(0), -1))


#########################################################
#########################################################
# Input extraction
resize = T.Compose([T.ToPILImage(), T.Grayscale(), T.Resize([74, 74]), T.ToTensor()])

def get_screen():
    # transpose into torch order (CHW)
    screen = env.render(mode='rgb_array').transpose((2, 0, 1))
    # Strip off the top and bottom of the screen
    screen = screen[:, 52:200, 6:154]
    # Convert to float, rescare, convert to torch tensor
    # (this doesn't require a copy)
    screen = np.ascontiguousarray(screen, dtype=np.float32) / 255
    screen = torch.from_numpy(screen)
    # Resize, and add a batch dimension (BCHW)
    output = resize(screen).unsqueeze(0).to(device)
    return output


#########################################################
#########################################################
# Training: Hyperparameters and utilities
BATCH_SIZE = 256
GAMMA = 0.999
EPS_START = 0.95
EPS_END = 0.05
EPS_DECAY = 200000
TARGET_UPDATE = 200

policy_net = DQN().to(device)
target_net = DQN().to(device)
target_net.load_state_dict(policy_net.state_dict())
target_net.eval()

optimizer = optim.RMSprop(policy_net.parameters(), lr=0.00001)
memory = ReplayMemory(100000)

steps_done = 0

def select_action(state):
    global steps_done
    sample = random.random()
    eps_threshold = EPS_END + (EPS_START - EPS_END) * \
        math.exp(-1. * steps_done / EPS_DECAY)
    steps_done += 1
    if sample > eps_threshold:
        with torch.no_grad():
            return policy_net(state).max(1)[1].view(1, 1)
    else:
        return torch.tensor([[random.randrange(2)]], device=device, dtype=torch.long)

episode_durations = []

def plot_durations():
    plt.figure(2)
    plt.clf()
    durations_t = torch.tensor(episode_durations, dtype=torch.float)
    plt.title('Training...')
    plt.xlabel('Episode')
    plt.ylabel('Duration')
    plt.plot(durations_t.numpy())
    # Take 100 episode averages and plot them too
    if len(durations_t) >= 100:
        means = durations_t.unfold(0, 100, 1).mean(1).view(-1)
        means = torch.cat((torch.zeros(99), means))
        plt.plot(means.numpy())

    plt.pause(0.001)  # pause a bit so that plots are updated
    if is_ipython:
        display.clear_output(wait=True)
        display.display(plt.gcf())

    if len(durations_t) % 10 == 0:
        plt.savefig('Duration_' + str(len(durations_t)) + '.png')


#########################################################
#########################################################
# Training: Training loop
def optimize_model():
    if len(memory) < BATCH_SIZE:
        return
    transitions = memory.sample(BATCH_SIZE)
    # Transpose the batch (see http://stackoverflow.com/a/19343/3343043 for
    # detailed explanation).
    batch = Transition(*zip(*transitions))

    # Compute a mask of non-final states and concatenate the batch elements
    non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                          batch.next_state)), device=device, dtype=torch.uint8)
    non_final_next_states = torch.cat([s for s in batch.next_state
                                                if s is not None])
    state_batch = torch.cat(batch.state)
    action_batch = torch.cat(batch.action)
    reward_batch = torch.cat(batch.reward)

    # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
    # columns of actions taken
    state_action_values = policy_net(state_batch).gather(1, action_batch)

    # Compute V(s_{t+1}) for all next states.
    next_state_values = torch.zeros(BATCH_SIZE, device=device)
    next_state_values[non_final_mask] = target_net(non_final_next_states).max(1)[0].detach()
    # Compute the expected Q values
    expected_state_action_values = (next_state_values * GAMMA) + reward_batch

    # Compute Huber loss
    loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

    # Optimize the model
    optimizer.zero_grad()
    loss.backward()
    for param in policy_net.parameters():
        param.grad.data.clamp_(-1, 1)
    optimizer.step()


#########################################################
#########################################################
# Training
num_episodes = 50000
for i_episode in range(num_episodes):
    # Initialize the environment and state
    print(i_episode)
    env.reset()
    env.step(1)
    last_screen = get_screen()
    current_screen = get_screen()
    state = 0.4*current_screen + 0.6*last_screen
    # state = current_screen
    for t in count():
        # Select and perform an action
        action = select_action(state)
        Action = action.item()
        Action += 2
        env.step(1)
        _, reward1, Done, info = env.step(Action)
        _, reward2, Done, info = env.step(Action)
        _, reward3, Done, info = env.step(Action)
        # env.render()
        reward = reward1 + reward2 + reward3
        reward = torch.tensor([reward], device=device)
      
        # Done or not
        if info['ale.lives'] > 4:
            done = False
        else:
            done = True

        if Done:
            done = True

        # Observe new state
        last_screen = current_screen
        current_screen = get_screen()
        if not done:
            next_state = 0.4*current_screen + 0.6*last_screen
            # next_state = current_screen
        else:
            next_state = None

        # Store the transition in memory
        memory.push(state, action, next_state, reward)

        # Move to the next state
        state = next_state

        # Perform one step of the optimization (on the target network)
        optimize_model()
        if done:
            episode_durations.append(t + 1)
            plot_durations()
            break
    # Update the target network
    if i_episode % TARGET_UPDATE == 0:
        target_net.load_state_dict(policy_net.state_dict())

    if i_episode % 1000 == 0:
        torch.save(policy_net.state_dict(), 'policy_net_' + str(i_episode) + '.pth')
        torch.save(target_net.state_dict(), 'target_net_' + str(i_episode) + '.pth')

print('Complete')
env.close()
plt.ioff()
plt.show()
