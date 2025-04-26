import logging
import os
import tempfile
from datetime import datetime

from pandas import DataFrame, ExcelWriter
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from config import get_error_key
from models import get_db, User
from utils.security import get_current_user

router = APIRouter()

@router.get("/export/data")
def export_database(
    background_tasks: BackgroundTasks,
    format: str = Query("csv", description="Format d'export (csv, excel, json, parquet, stata, pickle, feather, hdf)"),
    table: str = Query(None, description="Table spécifique à exporter (optionnel)"),
    filters: str = Query(None, description="Filtres au format JSON: {'colonne': 'valeur'} (optionnel)"),
    fields: str = Query(None, description="Champs spécifiques à exporter, séparés par des virgules (optionnel)"),
    limit: int = Query(None, description="Nombre maximum de lignes à exporter (optionnel)"),
    sort_by: str = Query(None, description="Colonne pour le tri des données (optionnel)"),
    sort_order: str = Query("asc", description="Ordre de tri (asc ou desc) (optionnel)"),
    compression: str = Query(None, description="Type de compression (zip, gzip, bz2, xz) pour formats supportés"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Configuration du logger
    logger = logging.getLogger(__name__)
    
    # Vérification des permissions
    user = db.query(User).filter(User.email == current_user['email']).first()
    if not user or user.role.lower() != 'admin':
        raise HTTPException(status_code=403, detail=get_error_key("db", "list", "no_permission"))
    
    # Formats supportés et leurs extensions et types MIME
    supported_formats = {
        "csv": {
            "extension": "csv",
            "mime": "text/csv",
            "multiple_tables": True,
            "export_func": lambda df, path: df.to_csv(path, index=False)
        },
        "excel": {
            "extension": "xlsx",
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "multiple_tables": True,
            "export_func": None  # Traité séparément pour Excel
        },
        "json": {
            "extension": "json",
            "mime": "application/json",
            "multiple_tables": True,
            "export_func": lambda df, path: df.to_json(path, orient="records", indent=4)
        },
        "parquet": {
            "extension": "parquet",
            "mime": "application/octet-stream",
            "multiple_tables": False,
            "export_func": lambda df, path: df.to_parquet(path, compression=compression or "snappy")
        },
        "stata": {
            "extension": "dta",
            "mime": "application/octet-stream",
            "multiple_tables": False,
            "export_func": lambda df, path: df.to_stata(path, write_index=False)
        },
        "pickle": {
            "extension": "pkl",
            "mime": "application/octet-stream",
            "multiple_tables": True,
            "export_func": lambda df, path: df.to_pickle(path, compression=compression)
        },
        "feather": {
            "extension": "feather",
            "mime": "application/octet-stream",
            "multiple_tables": False,
            "export_func": lambda df, path: df.to_feather(path, compression=compression)
        },
        "hdf": {
            "extension": "h5",
            "mime": "application/x-hdf5",
            "multiple_tables": True,
            "export_func": lambda df, path, key: df.to_hdf(path, key=key)
        }
    }
    
    # Validation du format demandé
    if format.lower() not in supported_formats:
        supported_list = ", ".join(supported_formats.keys())
        raise HTTPException(status_code=400, detail=f"Format non supporté. Utilisez l'un des formats suivants: {supported_list}")
    
    # Récupérer les informations sur le format sélectionné
    format_info = supported_formats[format.lower()]
    
    try:
        # Obtenir la liste des tables dans la base de données
        inspector = inspect(db.bind)
        db_tables = inspector.get_table_names()
        
        # Vérifier si la table demandée existe
        if table and table not in db_tables:
            raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
        
        # Tables à traiter
        tables_to_process = [table] if table else db_tables
        
        # Pour les formats qui ne supportent pas plusieurs tables, vérifier qu'une seule table est demandée
        if not format_info["multiple_tables"] and not table:
            raise HTTPException(
                status_code=400, 
                detail=f"Le format {format} ne supporte pas l'export de plusieurs tables simultanément. Veuillez spécifier une table."
            )
        
        # Créer un dictionnaire pour stocker les DataFrames
        dataframes = {}
        
        # Parseout JSON filters si fournis
        filter_dict = {}
        if filters:
            try:
                import json
                filter_dict = json.loads(filters)
                if not isinstance(filter_dict, dict):
                    raise HTTPException(status_code=400, detail="Les filtres doivent être au format JSON objet")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Format de filtres JSON invalide")
        
        # Traiter les champs spécifiques
        selected_fields = None
        if fields:
            selected_fields = [field.strip() for field in fields.split(',')]
        
        # Exporter chaque table
        for table_name in tables_to_process:
            # Construire la requête SQL
            
            # Sélection des champs
            if selected_fields:
                # Vérifier que les champs existent dans la table
                table_columns = [col['name'] for col in inspector.get_columns(table_name)]
                valid_fields = [f for f in selected_fields if f in table_columns]
                
                if not valid_fields:
                    logger.warning(f"Aucun champ valide trouvé pour la table {table_name}")
                    continue
                    
                select_clause = ", ".join(valid_fields)
            else:
                select_clause = "*"
            
            query = f"SELECT {select_clause} FROM {table_name}"
            
            # Ajouter les filtres
            where_conditions = []
            for column, value in filter_dict.items():
                # Vérifier si la colonne existe dans la table
                table_columns = [col['name'] for col in inspector.get_columns(table_name)]
                if column in table_columns:
                    where_conditions.append(f"{column} = :{column}")
            
            if where_conditions:
                query += " WHERE " + " AND ".join(where_conditions)
            
            # Ajouter le tri
            if sort_by:
                table_columns = [col['name'] for col in inspector.get_columns(table_name)]
                if sort_by in table_columns:
                    query += f" ORDER BY {sort_by} {'ASC' if sort_order.lower() == 'asc' else 'DESC'}"
            
            # Ajouter la limitation
            if limit and isinstance(limit, int) and limit > 0:
                query += f" LIMIT {limit}"
            
            # Exécuter la requête
            if where_conditions:
                # Créer un dictionnaire de paramètres pour les filtres
                params = {col: val for col, val in filter_dict.items() 
                         if col in [col['name'] for col in inspector.get_columns(table_name)]}
                result = db.execute(text(query), params)
            else:
                result = db.execute(text(query))
            
            # Convertir en liste de dictionnaires
            rows = [dict(row._mapping) for row in result]
            
            # Créer un DataFrame
            if rows:
                dataframes[table_name] = DataFrame(rows)
            else:
                dataframes[table_name] = DataFrame()  # DataFrame vide pour les tables sans données
        
        # Créer nom de fichier avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        table_suffix = f"_{table}" if table else "_all_tables"
        filename = f"database_export{table_suffix}_{timestamp}.{format_info['extension']}"
        
        # Créer un fichier temporaire pour stocker l'export
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)
        
        # Exporter selon le format demandé
        if format.lower() == "csv":
            # Pour CSV, on crée un seul fichier avec des séparateurs entre tables
            with open(file_path, 'w', encoding='utf-8') as f:
                for table_name, df in dataframes.items():
                    f.write(f"--- TABLE: {table_name} ---\n")
                    f.write(df.to_csv(index=False))
                    f.write("\n\n")
                    
        elif format.lower() == "excel":
            # Pour Excel, on utilise des feuilles différentes pour chaque table
            with ExcelWriter(file_path, engine='xlsxwriter') as writer:
                for table_name, df in dataframes.items():
                    # Limiter le nom de la feuille à 31 caractères (limite Excel)
                    sheet_name = table_name[:31]
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    
        elif format.lower() == "hdf":
            # Pour HDF, chaque table dans son propre groupe
            for table_name, df in dataframes.items():
                df.to_hdf(file_path, key=table_name, mode='a')
                
        elif format.lower() == "pickle" and len(dataframes) > 1:
            # Pour Pickle avec plusieurs tables, stocker le dictionnaire entier
            import pickle
            with open(file_path, 'wb') as f:
                pickle.dump(dataframes, f, protocol=pickle.HIGHEST_PROTOCOL)
                
        elif format.lower() == "json" and len(dataframes) > 1:
            # Pour JSON avec plusieurs tables, créer un objet JSON avec les tables comme clés
            import json
            with open(file_path, 'w', encoding='utf-8') as f:
                # Convertir chaque DataFrame en liste de dictionnaires
                json_dict = {table: df.to_dict(orient="records") for table, df in dataframes.items()}
                json.dump(json_dict, f, indent=4)
                
        else:
            # Pour les autres formats qui ne supportent qu'une seule table
            # ou pour les formats qui supportent plusieurs tables mais nous n'en avons qu'une
            table_name = list(dataframes.keys())[0]
            df = dataframes[table_name]
            
            if format.lower() == "json":
                df.to_json(file_path, orient="records", indent=4)
            elif format.lower() == "parquet":
                df.to_parquet(file_path, compression=compression or "snappy")
            elif format.lower() == "stata":
                df.to_stata(file_path, write_index=False)
            elif format.lower() == "pickle":
                df.to_pickle(file_path, compression=compression)
            elif format.lower() == "feather":
                df.to_feather(file_path, compression=compression)
        
        # Définir le type MIME approprié
        media_type = format_info["mime"]
        
        background_tasks.add_task(os.unlink, file_path)
        
        # Renvoyer le fichier en tant que réponse téléchargeable
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
            background=background_tasks  # Supprimer le fichier après envoi
        )
        
    except Exception as e:
        # Logs et gestion d'erreur
        logger.error(f"Erreur lors de l'export de la base de données: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'export de la base de données: {str(e)}"
        )