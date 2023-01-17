#!/usr/bin/env python3
import re
import os
import sys
import logging
import asyncio
import subprocess
import configparser
from datetime import datetime

get_loop = asyncio.get_running_loop if hasattr(asyncio, "get_running_loop") \
    else asyncio.get_event_loop
PEER_REGEX = re.compile(r"`(tcp|tls)://([a-z0-9\.\-\:\[\]]+):([0-9]+)`")

def get_peers(regions=None, countries=None):
    """Scan repository directory for peers"""
    assert os.path.exists(os.path.join(DATA_DIR, "README.md")), "Invalid path"
    peers = []

    if regions is None:
        regions = [d for d in os.listdir(DATA_DIR) if \
                os.path.isdir(os.path.join(DATA_DIR, d)) and \
                not d in [".git", "other"]]
    if countries is None:
        countries = []
        for region in regions:
            region_dir = os.path.join(DATA_DIR, region)
            countries += [f for f in os.listdir(region_dir) if f.endswith(".md")]
    else:
        countries = [country + ".md" for country in countries]

    for region in regions:
        for country in countries:
            cfile = os.path.join(DATA_DIR, region, country)
            if os.path.exists(cfile):
                with open(cfile, encoding="utf-8") as f:
                    for p in PEER_REGEX.findall(f.read()):
                        peers.append(
                            {"uri": p, "region": region, "country": country})
    return peers

async def resolve(name):
    """Get IP address or none to skip scan"""
    if name.startswith("["): return name[1:-1] # clear ipv6 address
    addr = name

    try:
        info = await get_loop().getaddrinfo(name, None)
        addr = info[0][4][0]
    except Exception as e:
        logging.debug("Resolve error %s: %s", type(e), e)
        addr = None

    return addr

async def isup(peer):
    """Check if peer is up and measure latency"""
    peer["up"] = False
    peer["latency"] = None
    addr = await resolve(peer["uri"][1])
    if addr:
        start_time = datetime.now()

        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(
                    addr, peer["uri"][2]), 5)
            peer["latency"] = datetime.now() - start_time
            writer.close()
            await writer.wait_closed()
            peer["up"] = True
        except Exception as e:
            logging.debug("Connection error %s: %s", type(e), e)

    return peer

def print_results(results):
    """Output results"""
    def prepare_table(peer_list_iter):
        """Prepare peers table for print"""
        addr_width = 0
        peers_table = []
        for p in peer_list_iter:
            addr = "{}://{}:{}".format(*p["uri"])
            latency = None
            if p["latency"] is not None:
                latency = round(p["latency"].total_seconds() * 1000, 3)
            place = "{}/{}".format(p["region"], p["country"])
            peers_table.append((addr, latency, place))
            # store max addr width
            if len(addr) > addr_width:
                addr_width = len(addr)
        return peers_table, addr_width

    print("\n=================================")
    print(" ALIVE PEERS (sorted by latency):")
    print("=================================")
    p_table, addr_w = prepare_table(filter(lambda p: p["up"], results))
    print("URI".ljust(addr_w), "Latency (ms)", "Location")
    print("---".ljust(addr_w), "------------", "--------")
    for p in sorted(p_table, key=lambda x: x[1]):
        print(p[0].ljust(addr_w), repr(p[1]).ljust(12), p[2])

    if SHOW_DEAD:
        print("\n============")
        print(" DEAD PEERS:")
        print("============")
        p_table, addr_w = prepare_table(filter(lambda p: not p["up"], results))
        print("URI".ljust(addr_w), "Location")
        print("---".ljust(addr_w), "--------")
        for p in p_table:
            print(p[0].ljust(addr_w), p[2])

async def main(regions=None, countries=None):
    """
    Main function.
    Get peers, state and print results.
    """
    try:
        peers = get_peers(regions=regions, countries=countries)
    except:
        print(f"Can't find peers in a directory: {DATA_DIR}")
        terminate()

    results = await asyncio.gather(*[isup(p) for p in peers])
    print_results(results)

def print_usage():
    """Print usage information"""
    print(f"\nUsage: {sys.argv[0]} [path to public_peers repository on a disk]")
    print("Flags:   -r <regions>    - set peers regions (split by ',')\n"
          "         -c <countries>  - set peers countries (split by ',')\n"
          "         -d              - show dead peers")
    print(f"Examples: {sys.argv[0]} ~/Projects/yggdrasil/public_peers\n"
          f"          {sys.argv[0]} -d ../public_peers -r europe")

def terminate():
    """Terminate app with help message"""
    print_usage()
    sys.exit()


if __name__ == "__main__":
    cfg = configparser.ConfigParser()
    cfg.read("peer_checker.conf")
    config = cfg["CONFIG"]

    DATA_DIR = config.get("data_dir")
    UPD_REPO = config.getboolean("update_repo")
    SHOW_DEAD = config.getboolean("show_dead")

    region_arg = config.get("regions_list").split()
    country_arg = config.get("countries_list").split()

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '-d':     # show dead peers flag
            SHOW_DEAD = True
        elif arg == '-r':   # set region flag
            i += 1
            try:
                region_arg = sys.argv[i].split(",")
            except:
                print('You use "-r" flag but did not set region')
                terminate()
        elif arg == '-c':   # set country flag
            i += 1
            try:
                country_arg = sys.argv[i].split(",")
            except:
                print('You use "-c" flag but did not set country')
                terminate()
        else:
            DATA_DIR = arg
        i += 1

    if not DATA_DIR:
        DATA_DIR = "public-peers"

    if not os.path.exists(DATA_DIR):
        subprocess.call(
            ["git", "clone", "--depth=1", config.get("repo_url"), DATA_DIR])
    elif UPD_REPO and os.path.exists(os.path.join(DATA_DIR, ".git")):
        print("Update public peers repository:")
        subprocess.call(["git", "-C", DATA_DIR, "pull"])

    print("\nReport date (UTC):", datetime.utcnow().strftime("%c"))
    asyncio.run(main(regions=region_arg, countries=country_arg))
