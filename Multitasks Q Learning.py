# -*- coding: utf-8 -*-
import numpy as np
from tensorflow.python.keras.layers import Dense, Dropout, Conv2D, MaxPooling2D, Activation, Flatten
import tensorflow as tf
from collections import deque
import random
from tqdm import tqdm
from PIL import Image
import cv2 as cv

# Enable GPU usage if device has available GPU
from tensorflow.python.client import device_lib
print(device_lib.list_local_devices())

# Global variables
DISCOUNT = 0.99
REPLAY_MEMORY_SIZE = 50_000  # How many last steps to keep for model training
MIN_REPLAY_MEMORY_SIZE = 1_000  # Minimum number of steps in a memory to start training
MINIBATCH_SIZE = 64  # How many steps (samples) to use for training
UPDATE_TARGET_EVERY = 5  # Terminal states (end of episodes)
MIN_REWARD = -200  # For model save
MEMORY_FRACTION = 0.20

# Environment settings
EPISODES = 20_000

# Exploration settings
epsilon = 1  # not a constant, going to be decayed
EPSILON_DECAY = 0.99975
MIN_EPSILON = 0.001

#  Stats settings
AGGREGATE_STATS_EVERY = 50  # episodes
SHOW_PREVIEW = False

# Model save setting
MODEL_NAME = 'AgentKerasV1'

class ObjectModel:
    def __init__(self, size):
        self.size = size
        self.x = np.random.randint(0, size)
        self.y = np.random.randint(0, size)

    def __str__(self):
        return f"An object with coordinate ({self.x}, {self.y})"

    def __sub__(self, other):
        return (self.x - other.x, self.y - other.y)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def action(self, choice):
        '''
        Gives us 9 total movement options. (0,1,2,3,4,5,6,7,8)
        '''
        if choice == 0:
            self.move(x=1, y=1)
        elif choice == 1:
            self.move(x=-1, y=-1)
        elif choice == 2:
            self.move(x=-1, y=1)
        elif choice == 3:
            self.move(x=1, y=-1)

        elif choice == 4:
            self.move(x=1, y=0)
        elif choice == 5:
            self.move(x=-1, y=0)

        elif choice == 6:
            self.move(x=0, y=1)
        elif choice == 7:
            self.move(x=0, y=-1)

        elif choice == 8:
            self.move(x=0, y=0)

    def move(self, x=False, y=False):

        # If no value for x, move randomly
        if not x:
            self.x += np.random.randint(-1, 2)
        else:
            self.x += x

        # If no value for y, move randomly
        if not y:
            self.y += np.random.randint(-1, 2)
        else:
            self.y += y

        # If we are out of bounds, fix!
        if self.x < 0:
            self.x = 0
        elif self.x > self.size - 1:
            self.x = self.size - 1
        if self.y < 0:
            self.y = 0
        elif self.y > self.size - 1:
            self.y = self.size - 1

class Environment:
    SIZE = 10
    RETURN_IMAGES = True
    MOVE_PENALTY = 1
    HAZARD_PENALTY = 300
    GOAL_REWARD = 25
    OBSERVATION_SPACE_VALUES = (SIZE, SIZE, 3)  # 4
    ACTION_SPACE_SIZE = 9
    EPISODE_STEP = 200
    TEST_EPISODE_STEP = 50
    PLAYER_COLOR = 1  # player key in dict
    GOAL_COLOR = 2  # goal key in dict
    HAZARD_COLOR = 3  # hazard key in dict
    # the dict! (colors)
    COLORS = {1: (255, 175, 0),
         2: (0, 255, 0),
         3: (0, 0, 255)}

    def reset(self):
        self.player = ObjectModel(self.SIZE)
        self.goal = ObjectModel(self.SIZE)
        while self.goal == self.player:
            self.goal = ObjectModel(self.SIZE)
        self.hazard = ObjectModel(self.SIZE)
        while self.hazard == self.player or self.hazard == self.goal:
            self.hazard = ObjectModel(self.SIZE)

        # # For testing only, fixed starting position for all objects, comment out for random starting position
        # # Comment out player.x, player.y for random start for player object
        # self.player.x = 1
        # self.player.y = 1
        # # Comment out hazard.x, hazard.y for random start for hazard object
        # self.hazard.x = 4
        # self.hazard.y = 3
        # # Comment out goal.x, goal.y for random start for goal object
        # self.goal.x = 8
        # self.goal.y = 3

        self.episode_step = 0

        if self.RETURN_IMAGES:
            observation = np.array(self.get_image())
        else:
            observation = (self.player - self.goal) + (self.player - self.hazard)
        return observation

    def step(self, action):
        self.episode_step += 1
        self.player.action(action)

        #### MAYBE ###
        # hazard.move()
        # goal.move()
        ##############

        if self.RETURN_IMAGES:
            new_observation = np.array(self.get_image())

        if self.player == self.hazard:
            reward = -self.HAZARD_PENALTY
        elif self.player == self.goal:
            reward = self.GOAL_REWARD
        else:
            reward = -self.MOVE_PENALTY

        finish = False
        if reward == self.GOAL_REWARD or reward == -self.HAZARD_PENALTY or self.episode_step >= self.EPISODE_STEP:
            finish = True

        return new_observation, reward, finish

    def render(self):
        img = self.get_image()
        img = cv.resize(img, (300, 300))  # resizing so we can see our agent in all its glory.
        cv.imshow("image", img)  # show it!
        cv.waitKey(500)

    # FOR CNN #
    def get_image(self):
        env = np.zeros((self.SIZE, self.SIZE, 3), dtype=np.uint8)  # starts an rbg of our size
        env[self.goal.x][self.goal.y] = self.COLORS[self.GOAL_COLOR]  # sets the goal location tile to green color
        env[self.hazard.x][self.hazard.y] = self.COLORS[self.HAZARD_COLOR]  # sets the hazard location to red
        env[self.player.x][self.player.y] = self.COLORS[self.PLAYER_COLOR]  # sets the player tile to blue
        return env

# Agent class
class DQNAgent:
    def __init__(self, test_agent_enable=False):

        # Main model for training
        self.trained_model = self.create_model()

        # Target network with initial weights as the main model
        self.target_model = self.create_model()
        self.target_model.set_weights(self.trained_model.get_weights())

        # Test network
        if test_agent_enable:
            self.test_model = tf.keras.models.load_model(MODEL_NAME)

        # An array with last n steps for training
        self.replay_memory = deque(maxlen=REPLAY_MEMORY_SIZE)

        # Used to count when to update target network with main network's weights
        self.target_update_counter = 0

    def create_model(self):
        model = tf.keras.Sequential()

        model.add(Conv2D(256, (3, 3),
                         input_shape=env.OBSERVATION_SPACE_VALUES))  # OBSERVATION_SPACE_VALUES = (10, 10, 3) a 10x10 RGB image.
        model.add(Activation('relu'))
        model.add(MaxPooling2D(pool_size=(2, 2)))
        model.add(Dropout(0.2))

        model.add(Conv2D(256, (3, 3)))
        model.add(Activation('relu'))
        model.add(MaxPooling2D(pool_size=(2, 2)))
        model.add(Dropout(0.2))

        model.add(Flatten())  # this converts our 3D feature maps to 1D feature vectors
        model.add(Dense(64))

        model.add(Dense(env.ACTION_SPACE_SIZE, activation='linear'))  # ACTION_SPACE_SIZE = how many choices (9)
        model.compile(loss="mse", optimizer=tf.keras.optimizers.Adam(lr=0.001), metrics=['accuracy'])
        return model

    # Adds step's data to a memory replay array
    # (observation space, action, reward, new observation space, finish)
    def update_replay_memory(self, transition):
        self.replay_memory.append(transition)

    # Trains main network every step during episode
    def train(self, terminal_state, step):

        # Start training only if certain number of samples is already saved
        if len(self.replay_memory) < MIN_REPLAY_MEMORY_SIZE:
            return

        # Get a minibatch of random samples from memory replay table
        minibatch = random.sample(self.replay_memory, MINIBATCH_SIZE)

        # Get current states from minibatch, then query NN trained_model for Q values
        current_states = np.array([transition[0] for transition in minibatch]) / 255
        current_qs_list = self.trained_model.predict(current_states)

        # Get future states from minibatch, then query NN target_model for Q values
        # When using target network, query it, otherwise main network should be queried
        next_states = np.array([transition[3] for transition in minibatch]) / 255
        future_qs_list = self.target_model.predict(next_states)

        # Create 2 list that store the state features and their corresponding label q action value
        state_features_list = []
        label_q_action_list = []

        # Now we need to enumerate our batches
        for index, (current_state, action, reward, next_states, finish) in enumerate(minibatch):

            # If not a terminal state, get new q from future states, otherwise set it to 0
            # almost like with Q Learning, but we use just part of equation here
            if not finish:
                max_future_q = np.max(future_qs_list[index])
                new_q = reward + DISCOUNT * max_future_q
            else:
                new_q = reward

            # Update Q value for given state
            current_qs = current_qs_list[index]
            current_qs[action] = new_q

            # And append to our training data to the lists
            state_features_list.append(current_state)
            label_q_action_list.append(current_qs)

        # Convert the lists into np array
        normalized_state_features_array = np.array(state_features_list) / 255 # Normalized state featured array of pixel
        label_q_action_array = np.array(label_q_action_list) 

        # Fit on all samples as one batch using label_q_action_array as the label to compute the loss of trained_model network
        self.trained_model.fit(normalized_state_features_array, label_q_action_array, batch_size=MINIBATCH_SIZE, verbose=0, shuffle=False)

        # Update target network counter every episode
        if terminal_state:
            self.target_update_counter += 1

        # If counter reaches set value, update target network with weights of main network
        if self.target_update_counter > UPDATE_TARGET_EVERY:
            self.target_model.set_weights(self.trained_model.get_weights())
            self.target_update_counter = 0

    # Queries main network for Q values given current observation space (environment state)
    def get_qs(self, state):
        # Reshape the state pixel array to contain batch dimension for feeding into Keras CNN
        reshape_state_array = state.reshape(-1, *state.shape)
        # Normalize the image by dividing over 255 (aka. max color range)
        prediction = self.trained_model.predict(reshape_state_array / 255)[0]
        return prediction

    # Queries main network for Q values given current observation space (environment state)
    def test_get_qs(self, state):
        # Reshape the state pixel array to contain batch dimension for feeding into Keras CNN
        reshape_state_array = state.reshape(-1, *state.shape)
        # Normalize the image by dividing over 255 (aka. max color range)
        prediction = self.test_model.predict(reshape_state_array / 255)[0]
        return prediction

# Create the environment and the learning agent
env = Environment()
# Only set test_agent_enable flag to true if you want to test the agent and there is a trained model already existed,
# this flag set to False by default
agent = DQNAgent(test_agent_enable=False)

for episode in tqdm(range(1, EPISODES + 1), ascii=True, unit='episodes'):

    # Restarting episode - reset episode reward and step number
    episode_reward = 0
    step = 1

    # Reset environment and get initial state
    current_state = env.reset()

    # Reset flag and start iterating until episode ends
    finish = False
    while not finish:

        # This part stays mostly the same, the change is to query a model for Q values
        if np.random.random() > epsilon:
            # Get action from Q table
            action = np.argmax(agent.get_qs(current_state))
        else:
            # Get random action
            action = np.random.randint(0, env.ACTION_SPACE_SIZE)

        next_state, reward, finish = env.step(action)

        # Transform new continous state to new discrete state and count reward
        episode_reward += reward

        if SHOW_PREVIEW and not episode % AGGREGATE_STATS_EVERY:
            env.render()

        # Every step we update replay memory and train main network
        agent.update_replay_memory((current_state, action, reward, next_state, finish))
        agent.train(finish, step)

        current_state = next_state
        step += 1

        # Save model, but only when min reward is greater or equal a set value
        if (episode+1) % 200 == 0:
            agent.trained_model.save(MODEL_NAME)

    # Decay epsilon
    if epsilon > MIN_EPSILON:
        epsilon *= EPSILON_DECAY
        epsilon = max(MIN_EPSILON, epsilon)