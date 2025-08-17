import pickle
from datetime import timedelta

from pathlib import Path
from typing import Final

from io_config.logger import LOGGER
from pretalx_api_wrapper.conference import CONFERENCE


class VoteManager:
    def __init__(self):
        self.vote_list: list = []
        self.votes: dict[str, int] = {}
        self.FILE_PREFIX: Final[str] = "votes_"
        self.votes_file: Path = Path(f"{self.FILE_PREFIX}{CONFERENCE.today}.pkl") # If you see this Path something went wrong
        self.update_vote_list()

# ----- main function keeping votes up to date past system crash -----
    def update_vote_list(self):
        if not CONFERENCE.update_tomorrow_events() and self.vote_list != []: # Only run this at midnight or at system start
            return False
        self.vote_list.clear()
        for event in CONFERENCE.tomorrow_events:
            if event['do_not_record']:
                continue
            presenter = 'Unknown'
            if event['persons']:  # Some rooms leave this as an empty list
                presenter = event['persons'][0]['name']
            event['persons'] = presenter
            self.vote_list.append(event)
        self.populate_votes()
        return True

    def get_vote_list(self):
        return self.vote_list

# ----- disk-io ------
    def populate_votes(self):
        if not self.load_votes_from_disk():
            for event in self.vote_list:
                self.votes.update({event['code']: 0})
        self.write_votes_to_disk()

    def load_votes_from_disk(self) -> bool:
        if not self.votes_file.is_file(): # If there is no file under this path
            LOGGER.warning(f"No votes file found at {str(self.votes_file.name)}. Creating a new one.")
            return False
        else:
            with open(self.votes_file, 'rb') as file:
                self.votes = pickle.load(file)
                LOGGER.info(f"Loaded {len(self.votes)} votes from {self.votes_file.name}")
            return True

    def write_votes_to_disk(self):
        self.votes_file = Path(f"{self.FILE_PREFIX}{CONFERENCE.today}")
        try:
            with open(self.votes_file, 'wb') as file:
                pickle.dump(self.votes, file)
        except IOError:
            raise IOError(f"Unable to write votes to {self.votes_file.name}")

# ----- vote endpoints ------
    def add_vote(self, event_code:str) -> int:
        self.votes[event_code] += 1
        LOGGER.info(f"Added vote to {event_code}.")
        self.write_votes_to_disk()
        return self.votes[event_code]

    def remove_vote(self, event_code:str) -> int:
        if self.votes[event_code] > 0:
            self.votes[event_code] -= 1
            self.write_votes_to_disk()
            return self.votes[event_code]
        else:
            raise ValueError(f"There are 0 votes for {event_code}.")

VOTE_MANAGER = VoteManager()