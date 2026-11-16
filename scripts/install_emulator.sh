#!/usr/bin/env bash
# Official AWS package only. For a disposable Ubuntu amd64 CI runner.
set -euo pipefail
task_dir="$(mktemp -d)"
package_url="https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator_amd64.deb"
curl --fail --silent --show-error --location "$package_url" -o "$task_dir/emulator.deb"
curl --fail --silent --show-error --location "$package_url.sig" -o "$task_dir/emulator.deb.sig"
curl --fail --silent --show-error --location https://downloads.aws.com/keys/gpg/current.asc -o "$task_dir/key.asc"
mkdir -m 700 "$task_dir/keyring"
gpg --homedir "$task_dir/keyring" --batch --import "$task_dir/key.asc"
fingerprint="$(gpg --homedir "$task_dir/keyring" --with-colons --fingerprint ssm-publishing@amazon.com | awk -F: '$1 == "fpr" {print $10; exit}')"
test "$fingerprint" = "98BCF336A3BE53B734E967C52E5BF49BD940F624"
gpg --homedir "$task_dir/keyring" --batch --verify "$task_dir/emulator.deb.sig" "$task_dir/emulator.deb"
mkdir -p reports/emulator
sha256sum "$task_dir/emulator.deb" | awk '{print $1}' > reports/emulator/package-sha256.txt
sudo apt-get install -y "$task_dir/emulator.deb"
