#!/bin/bash

source_folder="/mnt/g/Users/ROSINE/pictures"
destination_folder="/mnt/f/pictures"
count=1

find "$source_folder" -type f \( -iname \*.png -o -iname \*.jpg -o -iname \*.jpeg -o -iname \*.gif -o -iname \*.mov -o -iname \*.mp4 \) | while IFS= read -r filepath; do
    filename=$(basename "$filepath")
    destination_path="$destination_folder/$filename"
    counter=1

    while [[ -e "$destination_path" ]]; do
        base_name=${filename%.*}
        ext=${filename##*.}
        new_filename="${base_name}_$counter.$ext"
        destination_path="$destination_folder/$new_filename"
        counter=$((counter + 1))
    done
    echo $count
    count=$((count + 1))

    cp "$filepath" "$destination_path"
done