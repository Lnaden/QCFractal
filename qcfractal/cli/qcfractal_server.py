"""
A command line interface to the qcfractal server.
"""

import sys
import argparse
import secrets
import yaml
import shutil
import qcfractal

from ..config import DatabaseSettings, FractalConfig, FractalServerSettings
from ..postgres_manipulation import shutdown_postgres, initialize_postgres



def parse_args():
    parser = argparse.ArgumentParser(description='A CLI for the QCFractalServer.')
    subparsers = parser.add_subparsers(dest="cmd")

    # Init subcommands
    init = subparsers.add_parser('init', help="Initializes a QCFractal server and database information.")
    db_init = init.add_argument_group('Database Settings')
    for field in DatabaseSettings.field_names():
        cli_name = "--db-" + field.replace("_", "-")
        db_init.add_argument(cli_name, **DatabaseSettings.help_info(field))

    server_init = init.add_argument_group('Server Settings')
    for field in FractalServerSettings.field_names():
        cli_name = "--" + field.replace("_", "-")
        server_init.add_argument(cli_name, **FractalServerSettings.help_info(field))

    init.add_argument("--overwrite", action='store_true', help="Overwrites the current configuration file.")
    init.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))

    # Start subcommands
    start = subparsers.add_parser('start', help="Starts a QCFractal server instance.")
    start.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))
    for field in ["port", "logfile"]:
        cli_name = "--" + field.replace("_", "-")
        start.add_argument(cli_name, **FractalServerSettings.help_info(field))

    # Config subcommands
    config = subparsers.add_parser('config', help="Starts a QCFractal server instance.")
    config.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))


    # Move args around
    args = vars(parser.parse_args())

    ret = {}
    ret["database"] = {}
    ret["fractal"] = {}
    for key, value, in args.items():
        if value is None:
            continue

        if "db" in key:
            ret["database"][key.replace("db_", "")] = value
        elif key in FractalServerSettings.field_names():
            ret["fractal"][key] = value
        else:
            ret[key] = value

    if args["cmd"] is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return ret




def server_init(config):

    print("Initializing QCFractal configuration.")
    # Configuration settings

    config.base_path.mkdir(exist_ok=True)
    overwrite = args.get("overwrite", False)

    # Make sure we do not delete anything.
    if config.config_file_path.exists():
        print()
        if not overwrite:
            print("QCFractal configuration file already exists, to overwrite use '--overwrite' "
                  "or use the `qcfractal-server config` command line to alter settings.")
            sys.exit(2)
        else:
            print("!WARNING! A QCFractal configuration is currently initalized")
            print(f"!WARNING! Overwriting will delete all current Fractal data, this includes all data in {str(config.database_path)}.")
            print("!WARNING! Please use `qcfractal-server config` to alter configuration settings instead.")
            print()
            print("!WARNING! If you are sure you wish to procede please type 'REMOVEALLDATA' below.")
            # inp = input("  > ")
            inp = "REMOVEALLDATA"
            print()
            if inp == "REMOVEALLDATA":
                print("All data will be removed from the current QCFractal instance.")
                shutdown_postgres(config)
                shutil.rmtree(str(config.database_path), ignore_errors=True)
            else:
                print("Input does not match 'REMOVEALLDATA', exiting.")
                sys.exit(1)


    # WARNING! Passwords do not currently work.
    # if config.database.password is None:
    #     print("  Database password is None, generating a new private key.")
    #     config.database.password = secrets.token_urlsafe(16)


    print_config = config.dict()
    print_config["database"]["password"] = "**************"
    print_config = yaml.dump(print_config, default_flow_style=False)
    print("\n>>> Settings found:\n")
    print(print_config)

    print("\n>>> Setting up PostgreSQL...\n")
    config.database_path.mkdir(exist_ok=True)
    initialize_postgres(config, quiet=False)


    print("\n>>> Writing settings...")
    config.config_file_path.write_text(yaml.dump(config.dict(), default_flow_style=False))

    print("\n>>> Finishing up...")
    print("\n>>> Success! Please run `qcfractal-server start` to boot a FractalServer!")

def server_config(config):

    print(f"Displaying QCFractal configuration:\n")
    print(yaml.dump(config.dict(), default_flow_style=False))

def main(args=None):

    # Grab CLI args if not present
    if args is None:
        args = parse_args()
        print(args)

    cmd = args.pop("cmd")
    config = FractalConfig(**args)

    # Merge files
    if cmd != "init":
        if not config.base_path.exists():
            print(f"Could not find configuration file path: {config.base_path}")
            sys.exit(1)
        if not config.config_file_path.exists():
            print(f"Could not find configuration file: {config.config_file_path}")
            sys.exit(1)

        file_dict = FractalConfig(**yaml.load(config.config_file_path.read_text())).dict()
        config_dict = config.dict(skip_defaults=True)

        # Only fractal options can be changed by user input parameters
        file_dict["fractal"] = {**config_dict.pop("fractal"), **file_dict.pop("fractal")}

        config = FractalConfig(**file_dict)

    if cmd == "init":
        return server_init(config)
    elif cmd == "config":
        return server_config(config)
    raise Exception()

    # Handle SSL
    if args["disable_ssl"]:
        ssl_options = False
    else:
        ssl_certs = sum(args[x] is not None for x in ["tls_key", "tls_cert"])
        if ssl_certs == 0:
            ssl_options = True
        elif ssl_certs == 2:
            ssl_options = {"crt": args["tls_cert"], "key": args["tls_key"]}
        else:
            raise KeyError("Both tls-cert and tls-key must be passed in.")

    # Handle Adapters/QueueManagers
    exit_callbacks = []

    # Build an optional adapter
    if args["local_manager"]:
        ncores = args["local_manager"]
        if ncores == -1:
            ncores = None

        from concurrent.futures import ProcessPoolExecutor

        adapter = ProcessPoolExecutor(max_workers=ncores)

    else:
        adapter = None

    # Build the server itself
    server = qcfractal.FractalServer(
        name=args["server_name"],
        port=args["port"],
        compress_response=args["compress_response"],

        # Security
        security=args["security"],
        allow_read=args["allow_read"],
        ssl_options=ssl_options,

        # Database
        storage_uri=args["database_uri"],
        storage_project_name=args["database_name"],
        query_limit=args["query_limit"],

        # Log options
        logfile_prefix=args["log_prefix"],

        # Queue options
        heartbeat_frequency=args["heartbeat_frequency"],
        queue_socket=adapter)

    # Add exit callbacks
    for cb in exit_callbacks:
        server.add_exit_callback(cb[0], *cb[1], **cb[2])

    # Register closing
    cli_utils.install_signal_handlers(server.loop, server.stop)

    # Blocks until keyboard interupt
    server.start(start_periodics=args["start_periodics"])


if __name__ == '__main__':
    main()
