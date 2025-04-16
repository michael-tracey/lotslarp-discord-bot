# LotsLarp Discord Bot

This project is a Discord bot and a web UI that work together.

## Discord Bot

The Discord bot has the following commands:
* `/hello`: Greets the user in the Discord channel.
* `/throw`: Plays rock paper scissors with the user. If the user inputs 'random' for their throw, the bot will randomly choose.
* `/huh`: Searches a content database for a title. If a matching title is found, it will display the content. If no title is found, it will show similar titles.

## Web UI

The web UI displays a log of the commands that have been called, the user that called them, and the time they were called. It requires a login to use.
   
## Running the Application

This application uses supervisord to manage the Discord bot and web UI processes. To run the application, start supervisord. First build the docker image using `docker build -t lotslarp .` then run it using `docker compose up -d`.