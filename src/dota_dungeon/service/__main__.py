from .application import Config, run_service

if __name__ == "__main__":
    run_service(Config.from_env())
