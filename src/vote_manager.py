from pretalx_api_wrapper.conference import CONFERENCE


class VoteManager:
    def __init__(self):
        self.vote_list: list = []
        self.votes: dict[str, int] = {}
        self.update_vote_list()

    def update_vote_list(self):
        if not CONFERENCE.update_tomorrow_events() and self.vote_list != []:
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
        return True

    def add_vote(self, event):
        existing_votes = self.votes.get(event['code'])
        if existing_votes is not None:
            self.votes.update({event['code']: existing_votes+1})
        else:
            self.votes.update({event['code']: 1})
        print(self.votes)

VOTE_MANAGER = VoteManager()