#!/bin/bash
# Make a docker image from a Containerfile, unless the image of that tag was
# made from the same file: a label holds the file's hash. CI keeps the images
# between runs (.github/workflows/ci.yml), and an image that is kept is used
# as it is, so a run that changes no Containerfile builds no image.
#
# Usage: deploy/debian/image.sh TAG CONTAINERFILE
set -euo pipefail

tag=$1
recipe_file=$2
recipe=$(sha256sum "$recipe_file" | cut -d' ' -f1)
made=$(docker image inspect --format '{{ index .Config.Labels "segl.recipe" }}' "$tag" 2>/dev/null || true)
if [ "$made" = "$recipe" ]; then
    echo "image: $tag is made from this $recipe_file already"
    exit 0
fi
docker build --quiet --label "segl.recipe=$recipe" --tag "$tag" - <"$recipe_file" >/dev/null
