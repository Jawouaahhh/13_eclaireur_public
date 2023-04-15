import pandas as pd
import numpy as np
from pathlib import Path

# Charger les fichiers CSV
data_folder = Path("../../data/communities/")
infos_collectivites = pd.read_csv(data_folder / "processed_data/infos_collectivites.csv")
sirene_data = pd.read_csv(data_folder / "scrapped_data/sirene/download_20230413.csv", usecols=['siren', 'trancheEffectifsUniteLegale'])

# Jointure du nombre d'agents employés par les collectivités (sources SIRENE)
infos_collectivites = infos_collectivites.merge(sirene_data[['siren', 'trancheEffectifsUniteLegale']], left_on='SIREN', right_on='siren', how='left')
infos_collectivites.drop(columns=['siren'], inplace=True)

# Conversion de la colonne 'trancheEffectifsUniteLegale' en type numérique
infos_collectivites['trancheEffectifsUniteLegale'] = pd.to_numeric(infos_collectivites['trancheEffectifsUniteLegale'].astype(str), errors='coerce')

# Ajout de la variable EffectifsSup50, filtre légale d'application de l'open data par défaut (50 ETP agents)
infos_collectivites['EffectifsSup50'] = np.where(infos_collectivites['trancheEffectifsUniteLegale'] > 15, True, False)

# Filtrer les communes en fonction de la population et du nombre d'agents, tout en conservant les autres types de collectivités
filtered_collectivites = infos_collectivites.loc[
    (infos_collectivites['type'] != 'COM') |
    ((infos_collectivites['type'] == 'COM') &
     (infos_collectivites['population'] >= 3500) &
     (infos_collectivites['EffectifsSup50'] == True))
]

# Sauvegarder les données filtrées
filtered_collectivites.to_csv(data_folder / "processed_data/selected_communities.csv", index=False)
