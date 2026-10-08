import argparse

from .installed import load_installed_media, validate_installed_release


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the installed Dota card release")
    parser.add_argument("command", choices=["validate"])
    args = parser.parse_args(argv)
    try:
        release = validate_installed_release()
        media = load_installed_media(release)
    except (ValueError, OSError) as error:
        print(f"Validation failed: {error}")
        return 1
    print(f"{release.version} digest={release.digest} total=168 Doors=95 Treasures=73 media={media.media_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
