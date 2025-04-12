import random

class Throw:
    def __init__(self, template_env):
        self.template_env = template_env

    async def run(self, message):
        user_name = message.author.name
        user_throw = message.content.split()[1].lower() if len(message.content.split()) > 1 else ""

        if user_throw == "random":
            user_throw = random.choice(["rock", "paper", "scissors"])
        elif user_throw not in ["rock", "paper", "scissors"]:
            return "Invalid throw. Please enter rock, paper, scissors, or random."

        bot_throw = random.choice(["rock", "paper", "scissors"])



        if user_throw == bot_throw:
            result = "It's a tie!"
        elif (
            (user_throw == "rock" and bot_throw == "scissors")
            or (user_throw == "paper" and bot_throw == "rock")
            or (user_throw == "scissors" and bot_throw == "paper")
        ):
            result = f"{user_name} wins!"
        else:
            result = "I win!"

        template = self.template_env.get_template("throw_result.jinja2")  # Corrected template name
        return template.render(
            user_name=user_name, user_throw=user_throw, bot_throw=bot_throw, result=result
        )