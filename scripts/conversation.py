import openai

class Conversation:
    def __init__(self, api_key):
        self.api = openai.Client(api_key)
        self.context = []

    def start_conversation(self, message):
        response = self.api.chat\
            .create(\
                model="gpt-3.5-turkey", # or any other suitable model
                messages=[{"role": "user", "content": message}, {"role": "assistant", "content": ""}] # initial user message and assistant empty response
            ).choices[0].message["content"]
        self.context += [{"role": "user", "content": message}, {"role": "assistant", "content": response}]
        return response