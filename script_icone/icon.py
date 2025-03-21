import cv2
import numpy as np
import os
import shutil

def extract_icons(image_path, output_dir):
    # Charger l'image
    image = cv2.imread(image_path)
    
    # Convertir en niveaux de gris
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Appliquer un seuillage pour détecter les contours
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # Trouver les contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Trier les contours de gauche à droite, de haut en bas
    contours = sorted(contours, key=lambda c: (cv2.boundingRect(c)[1], cv2.boundingRect(c)[0]))
    
    # Créer le dossier de sortie
    os.makedirs(output_dir, exist_ok=True)
    
    # Extraire et enregistrer chaque icône
    for i, contour in enumerate(contours):
        x, y, w, h = cv2.boundingRect(contour)
        icon = image[y:y+h, x:x+w]
        icon_path = os.path.join(output_dir, f"icon_{i+1}.png")
        cv2.imwrite(icon_path, icon)
    
    print(f"Extraction terminée ! {len(contours)} icônes enregistrées dans {output_dir}")

if __name__ == "__main__":
    image_path = "icone_smash.png"  # Remplace par le chemin de ton image
    output_dir = "extracted_icons"       # Dossier de sortie
    extract_icons(image_path, output_dir)
