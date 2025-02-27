#!/usr/bin/env python3
import os
import sys
import argparse
from PIL import Image
from glob import glob
from time import time
from atexit import register
from platform import system
from plistlib import load, dump
from zipfile import ZipFile, BadZipFile
from shutil import rmtree, copyfile, copytree, move
from subprocess import run, DEVNULL, CalledProcessError
WORKING_DIR = os.getcwd()
USER_DIR = os.path.expanduser("~/.zxcvbn")
changed = 0

# check os compatibility
if (system := system()) == "Windows":
    print("windows is not currently supported. install wsl and use pyzule there.")
    sys.exit(1)

# set/get all args
parser = argparse.ArgumentParser(description="an azule \"clone\" written in python3.")
parser.add_argument("-i", metavar="input", type=str, required=True,
                    help="the .ipa/.app to patch")
parser.add_argument("-o", metavar="output", type=str, required=True,
                    help="the name of the patched .ipa/.app that will be created")
parser.add_argument("-n", metavar="name", type=str, required=False,
                    help="modify the app's name")
parser.add_argument("-v", metavar="version", type=str, required=False,
                    help="modify the app's version")
parser.add_argument("-b", metavar="bundle id", type=str, required=False,
                    help="modify the app's bundle id")
parser.add_argument("-m", metavar="minimum", type=str, required=False,
                    help="change MinimumOSVersion")
parser.add_argument("-c", metavar="level", type=int, default=6,
                    help="the compression level of the output ipa (default is 6)",
                    action="store", choices=range(1, 10),
                    nargs="?", const=1)
parser.add_argument("-k", metavar="icon", type=str, required=False,
                    help="an image file to use as the app icon")
parser.add_argument("-x", metavar="entitlements", type=str, required=False,
                    help="a file containing entitlements to sign the app with")
parser.add_argument("-l", metavar="plist", type=str, required=False,
                    help="a plist to merge with the existing Info.plist")
parser.add_argument("-r", metavar="url", type=str, required=False,
                    help="url schemes to add", nargs="+")
parser.add_argument("-f", metavar="files", nargs="+", type=str,
                    help="tweak files to inject into the ipa")
parser.add_argument("-u", action="store_true",
                    help="remove UISupportedDevices")
parser.add_argument("-w", action="store_true",
                    help="remove watch app")
parser.add_argument("-d", action="store_true",
                    help="enable files access")
parser.add_argument("-s", action="store_true",
                    help="fakesigns the ipa (for use with appsync)")
parser.add_argument("-e", action="store_true",
                    help="remove app extensions")
parser.add_argument("-p", action="store_true",
                    help="inject into @executable_path")
parser.add_argument("-t", action="store_true",
                    help="use substitute instead of substrate")
parser.add_argument("-z", action="store_true",
                    help="use 7zip instead of zip")
args = parser.parse_args()

# sanitize paths
args.i = os.path.normpath(args.i)
args.o = os.path.normpath(args.o)

# checking received args for errors
if not args.i.endswith(".ipa") and not args.i.endswith(".app"):
    parser.error("the input file must be an ipa/app")
elif not os.path.exists(args.i):
    parser.error(f"{args.i} does not exist")
elif not any((args.f, args.u, args.w, args.m, args.d, args.n, args.v, args.b, args.s, args.e, args.r, args.k, args.x, args.l)):
    parser.error("at least one option to modify the ipa must be present")
elif args.p and args.t:
    # well, you know, you CAN, but i just dont wanna implement that.
    # i would remove -p altogether but i already spent a considerable amount of time on it.
    parser.error("sorry, you can't use substitute while injecting into @executable_path")
elif args.m:
    for char in args.m:
        if char not in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "."):
            parser.error(f"invalid OS version: {args.m}")
elif args.k and not os.path.isfile(args.k):
    parser.error("the image file does not exist")
elif args.x and not os.path.isfile(args.x):
    parser.error("the entitlements file does not exist")
elif args.l and not os.path.isfile(args.l):
    parser.error("the plist to merge does not exist")

# further checking (no errors, just confirmation)
if not (args.o.endswith(".app") or args.o.endswith(".ipa")):
    print("[?] file extension not specified, creating ipa")
    args.o += ".ipa"
if os.path.exists(args.o):
    overwrite = input(f"[<] {args.o} already exists. overwrite? [Y/n] ").lower().strip()
    if overwrite in ("y", "yes", ""):
        del overwrite
    else:
        print("[>] quitting.")
        sys.exit()
EXTRACT_DIR = f".pyzule-{time()}"
REAL_EXTRACT_DIR = os.path.join(os.getcwd(), EXTRACT_DIR)

if args.f:
    if (nonexistant := ", ".join(ne for ne in args.f if not os.path.exists(ne))):
        # yes, TOTALLY required.
        if len(nonexistant.split(", ")) == 1:
            print(f"[!] {nonexistant} does not exist")
        else:
            print(f"[!] {nonexistant} do not exist")
        sys.exit(1)

    if args.p:
        inject_path = ""
        inject_path_exec = "@executable_path"
        print("[*] will inject into @executable_path")
    else:
        inject_path = "Frameworks"
        inject_path_exec = "@rpath"

    if args.t:
        print("[*] will use substitute instead of substrate")

if not args.o.endswith(".app") and args.z:
    if args.c != 6:
        print("[!] compression level will be ignored when using 7z")
    try:
        run(["7z"], check=True, stdout=DEVNULL, stderr=DEVNULL)
    except (CalledProcessError, FileNotFoundError):
        print("[!] 7z is not installed, either install it or don't use -z")
        sys.exit(1)
    print("[*] will use 7zip")


def get_plist(path, entry=None):
    with open(path, "rb") as f:
        if entry is None:
            return load(f)
        try:
            return load(f)[entry]
        except (IndexError, KeyError):
            return None


def dump_plist(path, new):
    with open(path, "wb") as f:
        dump(new, f)


def change_plist(success, error, plist, condition, *keys):
    try:
        if all(plist[key] == condition for key in keys):
            print(f"[?] {error}")
        else:
            raise KeyError
    except KeyError:
        for key in keys:
            plist[key] = condition
        print(f"[*] {success}")
        global changed  # skipcq: PYL-W0603
        changed = 1


def remove_dirs(app_path, removed, *names):
    removed_apps = 0

    for app in tuple(os.path.join(app_path, ap) for ap in names):
        try:
            rmtree(app)
            removed_apps = 1
        except FileNotFoundError:
            continue

    if removed_apps:
        print(f"[*] removed {removed}")
        global changed  # skipcq: PYL-W0603
        changed = 1
    else:
        print(f"[?] {removed} not present")


@register
def cleanup():
    print("[*] deleting temporary directory..")
    rmtree(REAL_EXTRACT_DIR)


# extracting ipa/copying app
INPUT_IS_IPA = 1 if args.i.endswith(".ipa") else 0
OUTPUT_IS_IPA = 1 if args.o.endswith(".ipa") else 0
if INPUT_IS_IPA:
    print("[*] extracting ipa..")
    try:
        os.makedirs(EXTRACT_DIR)
        with ZipFile(args.i, "r") as ipa:
            if not any(name.startswith("Payload/") for name in ipa.namelist()):
                raise KeyError
            ipa.extractall(path=EXTRACT_DIR)
    except KeyError:
        print("[!] couldn't find Payload folder, invalid ipa")
        sys.exit(1)
    except BadZipFile:
        print("[!] not a zip/ipa file")
        sys.exit(1)
    print("[*] extracted ipa")

# checking ipa/app validity
try:
    INPUT_BASENAME = os.path.basename(args.i)
    if INPUT_IS_IPA:
        APP_PATH = glob(os.path.join(EXTRACT_DIR, "Payload", "*.app"))[0]
    else:
        print("[*] copying app to temporary directory..")
        copytree(args.i, os.path.join(EXTRACT_DIR, INPUT_BASENAME))
        print("[*] copied app")
        APP_PATH = glob(os.path.join(EXTRACT_DIR, INPUT_BASENAME))[0]
    PLIST_PATH = glob(os.path.join(APP_PATH, "Info.plist"))[0]
    BINARY = get_plist(PLIST_PATH, "CFBundleExecutable")
    if system == "Linux":
        BINARY_PATH = os.path.join(APP_PATH, BINARY)
    else:
        BINARY_PATH = os.path.join(APP_PATH, BINARY).replace(" ", r"\ ")

    # checking encryption status
    if any("cryptid 1" in line for line in str(run(f"otool -l '{BINARY_PATH}'", capture_output=True, check=True, shell=True)).split("\\n")):
        print("[?] app is encrypted, the output app will only work for devices that have ever been logged in to your apple id")
        print("[?] find a decrypted ipa for everything to function normally")
except IndexError:
    print("[!] couldn't find .app folder and/or Info.plist file, invalid ipa/app specified")
    sys.exit(1)

# remove app extensions
if args.e:
    remove_dirs(APP_PATH, "app extensions", "PlugIns", "Extensions")

# injecting stuff
if args.f:
    ENT_PATH = os.path.join(APP_PATH, 'pyzule.entitlements')
    try:
        run(f"ldid -e {BINARY_PATH} > {ENT_PATH}", shell=True, check=True, stderr=DEVNULL)
        HAS_ENTITLEMENTS = 1 if os.path.getsize(ENT_PATH) > 0 else 0
    except CalledProcessError:
        with open(ENT_PATH, "w") as epf:
            HAS_ENTITLEMENTS = 0
        del epf
    finally:
        run(f"ldid -S {BINARY_PATH}", shell=True, check=True)
    DYLIBS_PATH = os.path.join(REAL_EXTRACT_DIR, "pyzule-inject")
    os.makedirs(DYLIBS_PATH, exist_ok=True)  # we'll copy everything we modify (dylibs) here to not mess with the original files

    args.f = [os.path.normpath(np) for np in args.f]

    if any(i.endswith(".appex") for i in args.f):
        os.makedirs(os.path.join(APP_PATH, "PlugIns"), exist_ok=True)

    if any(i.endswith(known) for i in args.f for known in (".deb", ".dylib", ".framework")):
        if inject_path:
            os.makedirs(os.path.join(APP_PATH, "Frameworks"), exist_ok=True)
            run(f"install_name_tool -add_rpath @executable_path/Frameworks {BINARY_PATH}", shell=True, stdout=DEVNULL, stderr=DEVNULL)   # skipcq: PYL-W1510
        deb_counter = 0

    common = (
        "libmryipc.dylib", "librocketboostrap.dylib", "cydiasubstrate.framework",
        "cephei.framework", "cepheiui.framework", "cepheiprefs.framework",
        "substitute.framework", "libhdev.framework"
    )
    dylibs = {d for d in args.f if d.endswith(".dylib") and not any(com in d.lower() for com in common)}
    id_injected = {f for f in args.f if ".framework" in f and not any(com in f.lower() for com in common)}
    id_injected.update(dylibs)

    # extracting all debs
    for deb in set(args.f):
        if not deb.endswith(".deb"):
            continue
        bn = os.path.basename(deb)
        output = os.path.join(EXTRACT_DIR, str(deb_counter))
        os.makedirs(output)
        os.makedirs(os.path.join(output, "e"))
        if system == "Linux":
            run(f"ar -x '{deb}' --output={output}", shell=True, check=True)
        else:
            run(f"tar -xf '{deb}' -C {output}", shell=True, check=True)
        data_tar = glob(os.path.join(output, "data.*"))[0]
        run(["tar", "-xf", data_tar, "-C", os.path.join(output, "e")], check=True)
        for dirpath, dirnames, filenames in os.walk(os.path.join(output, "e")):
            for filename in filenames:
                if filename.endswith(".dylib") and not any(com in filename.lower() for com in common) and not os.path.islink(os.path.join(dirpath, filename)):
                    src_path = os.path.join(dirpath, filename)
                    dest_path = os.path.join(DYLIBS_PATH, filename)
                    if not os.path.exists(dest_path):
                        move(src_path, dest_path)
                    dylibs.add(filename)
                    id_injected.add(filename)
            for dirname in dirnames:
                if dirname.endswith(".bundle") or (dirname.endswith(".framework") and not any(com in dirname.lower() for com in common)):
                    src_path = os.path.join(dirpath, dirname)
                    dest_path = os.path.join(DYLIBS_PATH, dirname)
                    if not os.path.exists(dest_path):
                        move(src_path, dest_path)
                    args.f.append(dirname)
                    if ".framework" in dirname:
                        id_injected.add(dirname)
                if "preferenceloader" in dirname.lower():
                    print(f"[!] found dependency on PreferenceLoader in {deb}, ipa might not work jailed")
        print(f"[*] extracted {bn}")
        deb_counter += 1

    args.f = set(args.f)
    needed = set()
    deps_info = {
        "substrate.": "CydiaSubstrate.framework/CydiaSubstrate",
        "librocketbootstrap.": "librocketbootstrap.dylib",
        "libmryipc.": "libmryipc.dylib",
        "cephei.": "Cephei.framework/Cephei",
        "cepheiui.": "CepheiUI.framework/CepheiUI",
        "cepheiprefs.": "CepheiPrefs.framework/CepheiPrefs",
        "libhdev.": "libhdev.framework/libhdev"
    }

    if args.t:
        deps_info["substrate."] = "Substitute.framework/Substitute"

    # remove codesign + fix all dependencies
    for dylib in dylibs:
        dylib_bn = os.path.basename(dylib)
        actual_path = os.path.join(DYLIBS_PATH, dylib_bn)
        try:
            copyfile(dylib, actual_path)
        except FileNotFoundError:
            pass
        run(f"ldid -S -M '{actual_path}'", shell=True, check=True)
        run(f"install_name_tool -id '{inject_path_exec}/{dylib_bn}' '{actual_path}'", shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)
        deps_temp = run(f"otool -L '{actual_path}'", shell=True, capture_output=True, text=True, check=True).stdout.strip().split("\n")[2:]
        for ind, dep in enumerate(deps_temp):
            if "(architecture " in dep:
                deps_temp = deps_temp[:ind]
                break

        deps = []
        for dep in deps_temp:
            if any(dep.startswith(s) for s in ("\t/Library/", "\t/usr/lib/", "\t@rpath", "\t@executable_path")):
                deps.append(dep.split()[0])

        for dep in deps_temp:
            dep = dep.split()[0]
            dep_actual_path = os.path.join(APP_PATH, inject_path, os.path.basename(dep))

            # check + fix dependencies on substrate, librocketbootstrap, libmryipc,
            # cephei, cepheiui, and cepheiprefs.
            for common_name, common_path in deps_info.items():
                if common_name in dep.lower():
                    run(f"install_name_tool -change {dep} {inject_path_exec}/{common_path} '{actual_path}'", shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)
                    needed.add(common_name)
                    if dep != f"{inject_path_exec}/{common_path}":
                        print(f"[*] fixed dependency in {os.path.basename(dylib)}: {dep} -> {inject_path_exec}/{common_path}")

        for dep in deps:
            for known in id_injected:
                if os.path.basename(known) in dep:
                    bn = os.path.basename(dep)

                    if f"{inject_path_exec}/{bn}" in dep:
                        continue

                    if dep.endswith(".dylib"):
                        run(f"install_name_tool -change {dep} {inject_path_exec}/{bn} '{actual_path}'", shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)
                        print(f"[*] fixed dependency in {os.path.basename(dylib)}: {dep} -> {inject_path_exec}/{bn}")
                    elif ".framework" in dep:
                        run(f"install_name_tool -change {dep} {inject_path_exec}/{bn}.framework/{bn} '{actual_path}'", shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)
                        print(f"[*] fixed dependency in {os.path.basename(dylib)}: {dep} -> {inject_path_exec}/{bn}.framework/{bn}")

    for missing in needed:
        real_dep_name = deps_info[missing].split("/")[0]
        if not os.path.exists(os.path.join(APP_PATH, inject_path, real_dep_name)):
            try:
                copytree(os.path.join(USER_DIR, real_dep_name), os.path.join(APP_PATH, inject_path, real_dep_name))
            except NotADirectoryError:
                copyfile(os.path.join(USER_DIR, real_dep_name), os.path.join(APP_PATH, inject_path, real_dep_name))
            print(f"[*] auto-injected {real_dep_name}")
        else:
            print(f"[*] existing {real_dep_name} found")

    # forgot about this earlier.. oops
    # yeah yeah, i know this fails if -p is used and dependencies need both substrate and rocketbootstrap,
    # but why would **anyone** be using -p in the first place? i dont see a reason to fix it.
    if "librocketbootstrap." in needed and "substrate." not in needed:
        if args.p or not args.t:
            if args.p:
                run("install_name_tool -change @rpath/CydiaSubstrate.framework/CydiaSubstrate " +
                f"@executable_path/CydiaSubstrate.framework/CydiaSubstrate '{os.path.join(APP_PATH, inject_path)}/librocketbootstrap.dylib'",
                shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)  # is this how im supposed to do it?
                print("[*] fixed dependency in librocketbootstrap.dylib: @rpath/CydiaSubstrate.framework/CydiaSubstrate -> @executable_path/CydiaSubstrate.framework/CydiaSubstrate")
            if os.path.exists(os.path.join(APP_PATH, inject_path, "CydiaSubstrate.framework")):
                print("[*] existing CydiaSubstrate.framework found, replacing")
                rmtree(os.path.join(APP_PATH, inject_path, "CydiaSubstrate.framework"))

            copytree(os.path.join(USER_DIR, "CydiaSubstrate.framework"), os.path.join(APP_PATH, inject_path, "CydiaSubstrate.framework"))
            print("[*] auto-injected CydiaSubstrate.framework")
        elif args.t:
            run("install_name_tool -change @rpath/CydiaSubstrate.framework/CydiaSubstrate " +
            f"@rpath/Substitute.framework/Substitute '{os.path.join(APP_PATH, inject_path)}/librocketbootstrap.dylib'",
            shell=True, check=True, stdout=DEVNULL, stderr=DEVNULL)  # repeating code? whaaat? nooo!!!
            print("[*] fixed dependency in librocketbootstrap.dylib: @rpath/CydiaSubstrate.framework/CydiaSubstrate -> @rpath/Substitute.framework/Substitute")

            if os.path.exists(os.path.join(APP_PATH, inject_path, "Substitute.framework")):
                print("[*] existing Substitute.framework found, replacing")
                rmtree(os.path.join(APP_PATH, inject_path, "Substitute.framework"))

            copytree(os.path.join(USER_DIR, "Substitute.framework"), os.path.join(APP_PATH, inject_path, "Substitute.framework"))
            print("[*] auto-injected Substitute.framework")

    for d in dylibs:
        actual_path = os.path.join(DYLIBS_PATH, os.path.basename(d))
        bn = os.path.basename(d)
        run(f"insert_dylib --inplace --no-strip-codesig --weak --all-yes '{inject_path_exec}/{bn}' '{BINARY_PATH}'", shell=True, stdout=DEVNULL, check=True)
        if os.path.exists(os.path.join(APP_PATH, inject_path, bn)):
            print(f"[*] existing {bn} found, replaced")
            os.remove(os.path.join(APP_PATH, inject_path, bn))
        else:
            print(f"[*] injected {bn}")
        copyfile(actual_path, os.path.join(APP_PATH, inject_path, bn))

    for tweak in args.f:
        bn = os.path.basename(tweak)
        actual_path = os.path.join(DYLIBS_PATH, os.path.basename(tweak))
        try:
            if bn.endswith(".framework") and "cydiasubstrate" not in bn.lower():
                try:
                    copytree(tweak, os.path.join(APP_PATH, inject_path, bn))
                    framework_exec = get_plist(os.path.join(tweak, "Info.plist"), "CFBundleExecutable")
                except FileNotFoundError:
                    copytree(actual_path, os.path.join(APP_PATH, inject_path, bn))
                    framework_exec = get_plist(os.path.join(actual_path, "Info.plist"), "CFBundleExecutable")
                run(f"insert_dylib --inplace --no-strip-codesig --weak --all-yes {inject_path_exec}/{bn}/{framework_exec} {BINARY_PATH}", shell=True, stdout=DEVNULL, check=True)
                print(f"[*] injected {bn}")
            elif bn.endswith(".appex"):
                copytree(tweak, os.path.join(APP_PATH, "PlugIns", bn))
                print(f"[*] copied {bn} to PlugIns")
            elif (
                tweak not in dylibs and not bn.endswith(".deb") and "cydiasubstrate" not in tweak.lower()
                and not any(com in tweak for com in common)
            ):
                try:
                    if os.path.isdir(tweak):
                        copytree(tweak, os.path.join(APP_PATH, bn))
                    else:
                        copyfile(tweak, os.path.join(APP_PATH, bn))
                except FileNotFoundError:
                    if os.path.isdir(actual_path):
                        copytree(actual_path, os.path.join(APP_PATH, bn))
                    else:
                        copyfile(actual_path, os.path.join(APP_PATH, bn))
                print(f"[*] copied {bn} to app root")
        except FileExistsError:
            continue

    if HAS_ENTITLEMENTS:
        run(f"ldid -S'{ENT_PATH}' {BINARY_PATH}", shell=True, check=True)
        print("[*] restored app entitlements")
    changed = 1

plist = get_plist(PLIST_PATH)

# removing UISupportedDevices (if specified)
if args.u:
    try:
        del plist["UISupportedDevices"]
        print("[*] removed UISupportedDevices")
        changed = 1
    except KeyError:
        print("[?] UISupportedDevices not present")

# removing watch app (if specified)
if args.w:
    remove_dirs(APP_PATH, "watch app", "Watch", "WatchKit", "com.apple.WatchPlaceholder")

# set minimum os version (if specified)
if args.m:
    change_plist(f"set MinimumOSVersion to {args.m}", f"MinimumOSVersion was already {args.m}",
                plist, args.m, "MinimumOSVersion")

# enable documents support
if args.d:
    change_plist("enabled documents support", "documents support was already enabled",
                plist, True, "UISupportsDocumentBrowser", "UIFileSharingEnabled")

# change app name
if args.n:
    change_plist(f"changed app name to {args.n}", f"app name was already {args.n}",
                plist, args.n, "CFBundleDisplayName", "CFBundleName")

# change app version
if args.v:
    change_plist(f"changed app version to {args.v}", f"app version was already {args.v}",
                plist, args.v, "CFBundleShortVersionString", "CFBundleVersion")

# change app bundle id
if args.b:
    orig_bundle = plist["CFBundleIdentifier"]
    plist["CFBundleIdentifier"] = args.b
    print(f"[*] changed bundle id: {orig_bundle} -> {args.b}")
    for ext in (PLUGINS := glob(os.path.join(APP_PATH, "PlugIns", "*.appex"))):
        appex_plist = get_plist((ext_plist := os.path.join(ext, "Info.plist")))
        appex_plist["CFBundleIdentifier"] = appex_plist["CFBundleIdentifier"].replace(orig_bundle, args.b)
        dump_plist(ext_plist, appex_plist)
    if PLUGINS:
        print("[*] changed all other bundle ids")
    changed = 1

# add url schemes to the app
if args.r:
    SCHEMES = [scheme.replace("://", "") for scheme in args.r]
    if "CFBundleURLTypes" not in plist:
        plist["CFBundleURLTypes"] = []
    plist["CFBundleURLTypes"].append({
        "CFBundleURLName": "fyi.zxcvbn.pyzule",
        "CFBundleURLSchemes": SCHEMES
    })
    print("[*] added url schemes:", ", ".join(SCHEMES))
    changed = 1

# "merge" plist content
# if theres stuff like arrays, this will just replace them instead of actually merging them
# why? because im lazy. and im 90% sure no one cares. if i (or someone else) needs it, i'll fix it
if args.l:
    args.l = os.path.normpath(args.l)  # skipcq: FLK-E741
    try:
        with open(args.l, "rb") as m:
            merge = load(m)
        not_new = []
        for k, v in merge.items():
            if k in plist and plist[k] == v:
                not_new.append(k)
            plist[k] = v
        if len(not_new) == len(merge):
            print("[?] no modified plist entries")
        else:
            print("[*] merged plist, modified keys:", ", ".join(k for k in merge.keys() if k not in not_new))
            changed = 1
    except Exception:  # skipcq: PYL-W0703 -- let's just hope this catches any parsing errors.
        print("[!] couldn't parse plist")

# change app icon - makes a new icon name, should hopefully
# force it to use the new icon instead of the one in cache
if args.k:
    args.k = os.path.normpath(args.k)
    IMG_PATH = os.path.join(EXTRACT_DIR, "pyzule_img.png")

    # convert to png
    if not args.k.endswith(".png"):
        with Image.open(args.k) as img:
            img.save(IMG_PATH, "PNG")
    else:
        copyfile(args.k, IMG_PATH)

    icon = f"pyzule_{int(time())}_"
    icon_60x60 = f"{icon}60x60"
    icon_76x76 = f"{icon}76x76"
    with Image.open(IMG_PATH) as img:
        img.resize((120, 120)).save(os.path.join(APP_PATH, f"{icon_60x60}@2x.png"), "PNG")
        img.resize((152, 152)).save(os.path.join(APP_PATH, f"{icon_76x76}@2x~ipad.png"), "PNG")

    plist["CFBundleIcons"] = {
        "CFBundlePrimaryIcon": {
            "CFBundleIconFiles": [icon_60x60],
            "CFBundleIconName": icon
        }
    }
    plist["CFBundleIcons~ipad"] = {
        "CFBundlePrimaryIcon": {
            "CFBundleIconFiles": [icon_60x60, icon_76x76],
            "CFBundleIconName": icon
        }
    }

    print("[*] updated app icon")
    changed = 1

dump_plist(PLIST_PATH, plist)

if args.s:
    print("[*] fakesigning..")
    run(f"ldid -S -M {BINARY_PATH}", shell=True, check=True)
    fs_counter = 1

    PATTERNS = (
        "*.dylib", "*.framework",
        os.path.join("PlugIns", "*.appex"),
        os.path.join("Extensions", "*.appex"),
        os.path.join("Frameworks", "*.dylib"),
        os.path.join("Frameworks", "*.framework")
    )
    tfs = sum((glob(os.path.join(APP_PATH, p)) for p in PATTERNS), [])

    for fs in tfs:
        if any(s in fs for s in (".framework", ".appex")):
            FS_EXEC = get_plist(os.path.join(fs, "Info.plist"), "CFBundleExecutable")
            run(f"ldid -S -M '{os.path.join(fs, FS_EXEC)}'", shell=True, check=True)
        else:
            run(f"ldid -S -M '{fs}'", shell=True, check=True)
        fs_counter += 1
    print(f"[*] fakesigned \033[1m{fs_counter}\033[0m items")
    changed = 1

# sign app executable with entitlements provided
if args.x:
    try:
        run(f"ldid -S'{os.path.normpath(args.x)}' {BINARY_PATH}", shell=True, check=True)
        print("[*] signed binary with entitlements file")
        changed = 1
    except CalledProcessError:
        print("[!] couldn't sign binary with entitlements")

# checking if anything was actually changed
if not changed:
    print("[!] nothing was changed, output will not be created")
    sys.exit()

# zipping everything back into an ipa/app
os.chdir(EXTRACT_DIR)
if OUTPUT_IS_IPA:
    if args.z:
        print("[*] generating ipa using 7z..")
    else:
        print(f"[*] generating ipa using compression level {args.c}..")
    if not INPUT_IS_IPA:
        os.makedirs("Payload")
        run(f"mv '{INPUT_BASENAME}' 'Payload/{INPUT_BASENAME}'", shell=True, check=True)
    if args.z:
        run(f"7z a '{os.path.basename(args.o)}' Payload", shell=True, check=True)
        print()  # just need a new line!
    else:
        run(f"zip -{args.c} -r '{os.path.basename(args.o)}' Payload", shell=True, stdout=DEVNULL, check=True)
else:
    print("[*] moving app to output..")

# cleanup when everything is done
os.chdir(WORKING_DIR)
if "/" in args.o:
    os.makedirs(args.o.replace(os.path.basename(args.o), ""), exist_ok=True)
if OUTPUT_IS_IPA:
    move(os.path.join(EXTRACT_DIR, os.path.basename(args.o)), args.o)
    print(f"[*] generated ipa at {args.o}")
else:
    run(f"mv '{APP_PATH}' '{os.path.join(EXTRACT_DIR, os.path.basename(args.o))}'", shell=True, stderr=DEVNULL)  # skipcq: PYL-W1510
    if os.path.exists(args.o):
        rmtree(args.o)
    run(f"mv '{os.path.join(EXTRACT_DIR, os.path.basename(args.o))}' '{args.o}'", shell=True, check=True)
    print(f"[*] generated app at {args.o}")
