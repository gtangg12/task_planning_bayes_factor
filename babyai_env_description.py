import random
import itertools
import inspect
from collections import Counter, defaultdict

import torch
from babyai.common import *

from datasets.formats.task_sequence import TaskSequence


EGO_ROW = VIEW_SHAPE[0] - 1
EGO_COL = VIEW_SHAPE[1] // 2
EGO = 'E'

EGO_VIEW_ENCODINGS = {
    'cardinal_diagonal': (
        """
        6663777
        6663777
        6663777
        6663777
        6663777
        6660777
        441E255
        """,
        {
            '0': 'Directly front',
            '1': 'Directly left',
            '2': 'Directly right',
            '3': 'Farther front',
            '4': 'Farther left',
            '5': 'Farther right',
            '6': 'Farther front left',
            '7': 'Farther front right'
        }
    )
}


def make_view_partition(view_encoding: str) -> list[tuple[int, int]]:
    """ Generate view encoding from the perspective of the ego agent.
        Resulting dict: { statement : [(r, c)...] }
    """
    partition_dict = defaultdict(list)

    encoding_labels, label_to_statement = EGO_VIEW_ENCODINGS[view_encoding]

    encoding_labels = inspect.cleandoc(encoding_labels).split('\n')
    n, m = len(encoding_labels), len(encoding_labels[0])
    assert (n, m) == VIEW_SHAPE, 'Region pattern must be same as ego view shape.'

    for (r, c) in itertools.product(range(n), range(m)):
        label = encoding_labels[r][c]
        if label == EGO:
            continue
        statement = label_to_statement[label]
        partition_dict[statement].append((r, c))

    partitions = []
    for _, statement in sorted(list(label_to_statement.items())):
        partitions.append((statement, partition_dict[statement]))
    return partitions


def location_descriptors(image: torch.Tensor, r: int, c: int):
    """ Return object, color, and door descriptors of frame[i, j] """
    x, y, z = image[r, c]
    return OBJECTS[x], COLORS[y], DOOR_STATES[z]


def location_string(image: torch.tensor, r: int, c: int):
    """ Generate description phrase of frame[i, j] """
    object, color, door = location_descriptors(image, r, c)
    if object == 'unseen':
        return 'unseen'
    elif object in ['empty', 'floor']:
        return 'empty'
    elif object == 'door':
        return f'{door} {color} {object}'
    return f'{color} {object}'


def region_description(image: torch.Tensor, region: list[tuple[int, int]]) -> str:
    """ Helper function to generate a grammatically correct description of a region, 
        a list of coordinate tuples """
    description = []

    # tally entities
    entities = Counter()
    for i, j in region:
        entry = location_string(image, i, j)
        entities[entry] += 1
    if set(entities.keys()).issubset({'unseen', 'empty'}):
        return 'the space is empty.' if 'empty' in entities else 'the space is not visible.'
        
    # generate description, putting walls at the end of the description
    entities_walls_last = sorted(list(entities.items()), key=lambda x: 1 if 'wall' in x else 0)
    for i, (entity, count) in enumerate(entities_walls_last):
        if entity == 'unseen' or entity == 'empty':
            continue
        if count > 1:
            plural = 'es' if 'box' in entity else 's'
            description.append(f'{count} {entity}{plural}')
        else:
            description.append(f'a {entity}')

    # proper grammar
    if len(description) > 1:
        tail = ', '.join(description[:-1]) + ' and ' + description[-1]
    else:
        tail = description[0]
    linking_verb = 'is' if tail[0] == 'a' else 'are'
    return f'{linking_verb} {tail}.'
    

def image_description(image: torch.tensor, view_partition) -> str:
    """ Generate a verbal description of the actor's current state based on view encoding """
    description = ['You are in a room.']

    for statement, region in view_partition:
        description.append(statement)
        description.append(region_description(image, region))
    return ' '.join(description)


class TaskSequencePromptBuilder():
    def __init__(self, sequence: TaskSequence, view_encoding: str):
        self.sequence = sequence
        self.view_partition = make_view_partition(view_encoding)
        
        # inventory over time
        self.inventory_history = []
        cur_item = None
        for frame in range(sequence.sequence):
            cur_action = frame.actions['name']
            if cur_action == 'pickup':
                cur_item = location_string(frame.features['images'])
            elif cur_action == 'drop':
                cur_item = None
            self.inventory_history.append(cur_item)
    
    def build_prompt(self, timestamp: int):
        """ Generate a verbal description of the actor's current state """
        image = self.sequence.sequence[timestamp].features['images']
        description = [image_description(image, self.view_partition)]
        if self.inventory_history[timestamp]:
            description.append(f'You are carrying a {self.inventory_item}.')
        else:
            description.append('You are not carrying anything.')
        return ' '.join(description)
    
    def action_taken(self, timestamp):
        """ Return the action taken by the actor given the current state """
        action = self.sequence.sequence[timestamp].features.actions['name']
        return ACTIONS[action]


def generate_env_description_sample(sequence, view_encoding='cardinal_diagonal'):
    """ Generate a sample of textual descriptions from a sequence """    
    timestamp = random.randint(0, sequence.n_frames - 1)
    
    generator = TaskSequencePromptBuilder(sequence, view_encoding)

    prompt = generator.build_prompt(timestamp)
    action = generator.action_taken(timestamp)
    return prompt, action
