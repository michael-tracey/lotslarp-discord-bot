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

### Google Cloud Authentication (for Local Development)

To run the bot locally with Firestore integration, you need to authenticate your machine with Google Cloud. This is not required when deployed to Cloud Run, as authentication is handled automatically.

1.  Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install).
2.  Log in to your Google account:
    ```bash
    gcloud auth login
    ```
3.  Set up Application Default Credentials (ADC). This is what the Python client library uses to authenticate locally.
    ```bash
    gcloud auth application-default login
    ```
4.  Ensure your local environment is pointed to the correct project:
    ```bash
    gcloud config set project YOUR_PROJECT_ID
    ```
