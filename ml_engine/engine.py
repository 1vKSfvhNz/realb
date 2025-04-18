import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import logging
import os
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import threading
import time
import datetime
import schedule

from models import UserPreferenceProfile, Order, Product, Banner, get_db

class UserInterestPredictor:
    def __init__(self):
        """
        Initialise le prédicteur d'intérêts utilisateur
        """
        # Configuration du logging
        logging.basicConfig(level=logging.INFO, 
                            format='%(asctime)s - %(levelname)s: %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Modèle de machine learning
        self.model = None
        self.preprocessor = None
        self.model_filepath = 'user_interest_model.joblib'
        self.last_training_time = None
        self.model_performance = None
        
        # Planificateur pour l'entraînement automatique
        self.scheduler_thread = None
        self.scheduler_running = False
        
        # Essayer de charger un modèle existant au démarrage
        self.load_model()
    
    def start_scheduler(self, training_time="02:00"):
        """
        Démarre le planificateur pour entraîner le modèle à une heure précise chaque jour
        
        :param training_time: Heure d'entraînement au format "HH:MM"
        """
        # S'assurer que tout planificateur existant est arrêté
        self.stop_scheduler()
        
        self.scheduler_running = True
        
        # Effacer les tâches existantes et planifier l'entraînement à l'heure spécifiée
        schedule.clear()
        schedule.every().day.at(training_time).do(self.scheduled_training)
        
        self.logger.info(f"Entraînement planifié tous les jours à {training_time}")
        
        # Démarrer le thread pour le planificateur
        self.scheduler_thread = threading.Thread(target=self._run_scheduler)
        self.scheduler_thread.daemon = True  # Le thread s'arrêtera quand le programme principal s'arrête
        self.scheduler_thread.start()
    
    def _run_scheduler(self):
        """
        Fonction exécutée dans un thread séparé pour gérer le planificateur
        """
        while self.scheduler_running:
            schedule.run_pending()
            time.sleep(60)  # Vérifier toutes les minutes
    
    def stop_scheduler(self):
        """
        Arrête le planificateur d'entraînement
        """
        self.scheduler_running = False
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=2)
            self.logger.info("Planificateur arrêté")
    
    def scheduled_training(self):
        """
        Fonction appelée par le planificateur pour entraîner le modèle
        """
        self.logger.info("Démarrage de l'entraînement planifié")
        
        # Obtenir une session de base de données
        db = next(get_db())
        try:
            success = self.train_model(db)
            if success:
                self.save_model()
                self.last_training_time = datetime.datetime.now()
                self.logger.info("Entraînement planifié terminé avec succès")
            else:
                self.logger.warning("Échec de l'entraînement planifié - données insuffisantes")
        except Exception as e:
            self.logger.error(f"Erreur lors de l'entraînement planifié : {e}")
        finally:
            db.close()
    
    def get_model_status(self) -> Dict:
        """
        Retourne le statut actuel du modèle
        
        :return: Dictionnaire contenant les informations sur le modèle
        """
        return {
            "model_loaded": self.model is not None,
            "last_training_time": self.last_training_time.isoformat() if self.last_training_time else None,
            "model_performance": self.model_performance,
            "scheduler_running": self.scheduler_running
        }
    
    def extract_user_features(self, db: Session) -> pd.DataFrame:
        """
        Extrait les caractéristiques des utilisateurs à partir de la base de données
        
        :param db: Session de base de données SQLAlchemy
        :return: DataFrame avec les caractéristiques des utilisateurs
        """
        try:
            # Récupérer tous les profils utilisateurs
            profiles = db.query(UserPreferenceProfile).all()
            
            if not profiles:
                self.logger.warning("Aucun profil utilisateur trouvé dans la base de données")
                return pd.DataFrame()
            
            # Construire le DataFrame
            data = []
            for profile in profiles:
                # Vérifier les attributs obligatoires
                if not hasattr(profile, 'total_orders') or profile.total_orders is None:
                    continue
                    
                if not hasattr(profile, 'average_order_value') or profile.average_order_value is None:
                    continue
                
                # Déterminer le niveau d'engagement
                engagement_level = self._calculate_engagement_level(profile)
                
                # Convertir les arrays en chaînes pour le traitement
                currencies = ','.join(profile.preferred_currencies) if profile.preferred_currencies else ''
                
                # Convertir la liste d'IDs produits en chaîne
                product_ids = ','.join(map(str, profile.preferred_product_ids)) if profile.preferred_product_ids else ''
                
                # Temps d'achat préféré avec valeur par défaut
                preferred_time = profile.preferred_purchase_time if profile.preferred_purchase_time else 'Unknown'
                
                # Ajouter les caractéristiques à la liste
                data.append({
                    'user_id': profile.user_id,
                    'total_orders': profile.total_orders,
                    'average_order_value': profile.average_order_value,
                    'top_category': profile.most_purchased_category_id or 0,
                    'preferred_purchase_time': preferred_time,
                    'currencies': currencies,
                    'product_ids': product_ids,
                    'engagement_level': engagement_level
                })
            
            df = pd.DataFrame(data)
            self.logger.info(f"Extraction réussie : {len(df)} profils utilisateurs")
            return df
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'extraction des données : {e}")
            return pd.DataFrame()  # Retourner un DataFrame vide en cas d'erreur
    
    def _calculate_engagement_level(self, profile: UserPreferenceProfile) -> str:
        """
        Calcule le niveau d'engagement d'un utilisateur selon ses caractéristiques
        
        :param profile: Profil utilisateur
        :return: Niveau d'engagement (Low, Medium, High)
        """
        # Valeurs par défaut
        total_orders = getattr(profile, 'total_orders', 0) or 0
        avg_order_value = getattr(profile, 'average_order_value', 0) or 0
        
        # Score d'engagement basé sur le nombre de commandes et la valeur moyenne
        engagement_score = total_orders * 0.7 + (avg_order_value / 100) * 0.3
        
        if engagement_score > 10:
            return 'High'
        elif engagement_score > 5:
            return 'Medium'
        else:
            return 'Low'
    
    def prepare_data(self, df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], 
                                                     Optional[pd.Series], Optional[pd.Series]]:
        """
        Prépare les données pour l'entraînement du modèle
        
        :param df: DataFrame des caractéristiques utilisateurs
        :return: Tuple de (X_train, X_test, y_train, y_test) ou (None, None, None, None) si données insuffisantes
        """
        if df.empty:
            self.logger.warning("DataFrame vide, impossible de préparer les données")
            return None, None, None, None
        
        # Vérifier le nombre minimum d'échantillons
        min_samples_per_class = 3  # Au moins 3 exemples par classe pour l'entraînement
        class_counts = df['engagement_level'].value_counts()
        
        if len(df) < 10 or any(count < min_samples_per_class for count in class_counts.values):
            self.logger.warning(f"Données insuffisantes pour l'entraînement ({len(df)} échantillons)")
            self.logger.info(f"Distribution des classes: {class_counts.to_dict()}")
            return None, None, None, None
            
        # Sélection des caractéristiques
        features = [
            'total_orders', 
            'average_order_value', 
            'top_category', 
            'preferred_purchase_time'
        ]
        
        # Vérifier que toutes les colonnes existent
        for feature in features:
            if feature not in df.columns:
                self.logger.error(f"Colonne {feature} manquante dans le DataFrame")
                return None, None, None, None
        
        # Encodage des caractéristiques catégorielles
        categorical_features = ['preferred_purchase_time']
        numerical_features = ['total_orders', 'average_order_value', 'top_category']
        
        # Prétraitement des données avec gestion des valeurs manquantes
        preprocessor = ColumnTransformer(
            transformers=[
                ('num', StandardScaler(), numerical_features),
                ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_features)
            ],
            remainder='drop'  # Ignorer les autres colonnes
        )
        
        # Préparation des données
        X = df[features].copy()
        y = df['engagement_level'].copy()
        
        # Remplacer les valeurs manquantes dans les données numériques
        for col in numerical_features:
            X[col] = X[col].fillna(0)
        
        # Remplacer les valeurs manquantes dans les données catégorielles
        for col in categorical_features:
            X[col] = X[col].fillna('Unknown')
        
        # Division des données avec stratification pour conserver la distribution des classes
        try:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            self.preprocessor = preprocessor
            return X_train, X_test, y_train, y_test
            
        except ValueError as e:
            self.logger.error(f"Erreur lors de la division des données: {e}")
            return None, None, None, None
    
    def train_model(self, db: Session) -> bool:
        """
        Entraîne un modèle de forêt aléatoire pour prédire l'engagement
        
        :param db: Session de base de données SQLAlchemy
        :return: True si l'entraînement a réussi, False sinon
        """
        try:
            # Extraction et préparation des données
            df = self.extract_user_features(db)
            if df.empty:
                self.logger.warning("Aucune donnée extraite pour l'entraînement")
                return False
                
            X_train, X_test, y_train, y_test = self.prepare_data(df)
            
            if X_train is None:
                self.logger.warning("Préparation des données échouée")
                return False
            
            # Pipeline de machine learning
            pipeline = Pipeline([
                ('preprocessor', self.preprocessor),
                ('classifier', RandomForestClassifier(
                    n_estimators=100, 
                    random_state=42, 
                    class_weight='balanced',
                    n_jobs=-1  # Utiliser tous les processeurs disponibles
                ))
            ])
            
            # Entraînement du modèle
            pipeline.fit(X_train, y_train)
            
            # Évaluation du modèle
            y_pred = pipeline.predict(X_test)
            
            # Stocker les métriques de performance
            report = classification_report(y_test, y_pred, output_dict=True)
            self.model_performance = {
                'accuracy': report['accuracy'],
                'weighted_f1': report['weighted avg']['f1-score'],
                'class_report': report,
                'confusion_matrix': confusion_matrix(y_test, y_pred).tolist(),
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            self.logger.info(f"Performance du modèle: Accuracy={report['accuracy']:.4f}, F1={report['weighted avg']['f1-score']:.4f}")
            
            # Matrice de confusion pour le débogage
            conf_matrix = confusion_matrix(y_test, y_pred)
            self.logger.info(f"Matrice de confusion:\n{conf_matrix}")
            
            self.model = pipeline
            self.last_training_time = datetime.datetime.now()
            return True
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'entraînement du modèle : {e}")
            return False
    
    def predict_user_interest(self, user_id: int, db: Session) -> Dict:
        """
        Prédit le niveau d'intérêt d'un utilisateur et génère des recommandations
        
        :param user_id: ID de l'utilisateur
        :param db: Session de base de données SQLAlchemy
        :return: Dictionnaire avec les prédictions et recommandations
        """
        try:
            # Vérifier si le modèle est disponible, sinon essayer de le charger
            if self.model is None:
                model_loaded = self.load_model()
                
                if not model_loaded:
                    self.logger.warning("Aucun modèle n'est disponible. Tentative d'entraînement...")
                    training_success = self.train_model(db)
                    if not training_success:
                        return {
                            'success': False,
                            'message': 'Impossible de prédire - données insuffisantes pour l\'entraînement',
                            'engagement_level': 'Unknown',
                            'recommendations': self._get_fallback_recommendations(db, user_id)
                        }
            
            # Récupérer le profil de l'utilisateur
            profile = db.query(UserPreferenceProfile).filter(UserPreferenceProfile.user_id == user_id).first()
            
            if not profile:
                return {
                    'success': False,
                    'message': 'Profil utilisateur non trouvé',
                    'engagement_level': 'Unknown',
                    'recommendations': self._get_fallback_recommendations(db, user_id)
                }
            
            # Vérifier si le profil a les caractéristiques minimales nécessaires
            if not hasattr(profile, 'total_orders') or profile.total_orders is None:
                return {
                    'success': False,
                    'message': 'Profil utilisateur incomplet',
                    'engagement_level': 'Unknown',
                    'recommendations': self._get_fallback_recommendations(db, user_id)
                }
            
            # Préparer les caractéristiques pour la prédiction
            user_features = pd.DataFrame({
                'total_orders': [profile.total_orders],
                'average_order_value': [profile.average_order_value or 0],
                'top_category': [profile.most_purchased_category_id or 0],
                'preferred_purchase_time': [profile.preferred_purchase_time or 'Unknown']
            })
            
            # Prédire le niveau d'engagement
            try:
                interest_level = self.model.predict(user_features)[0]
            except Exception as e:
                self.logger.error(f"Erreur lors de la prédiction du niveau d'engagement : {e}")
                interest_level = self._calculate_engagement_level(profile)
            
            # Générer des recommandations basées sur le niveau d'engagement et les préférences
            recommendations = self.generate_recommendations(profile, interest_level, db)
            
            return {
                'success': True,
                'engagement_level': interest_level,
                'recommendations': recommendations
            }
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la prédiction : {e}")
            return {
                'success': False,
                'message': f"Erreur lors de la prédiction : {str(e)}",
                'engagement_level': 'Unknown',
                'recommendations': self._get_fallback_recommendations(db, user_id)
            }
    
    def _get_fallback_recommendations(self, db: Session, user_id: int) -> List[Dict]:
        """
        Génère des recommandations de repli basées sur les produits populaires
        quand les recommandations personnalisées ne sont pas disponibles
        
        :param db: Session de base de données
        :param user_id: ID de l'utilisateur
        :return: Liste de recommandations
        """
        self.logger.info(f"Utilisation de recommandations de repli pour l'utilisateur {user_id}")
        
        try:
            # Récupérer les produits les plus populaires
            popular_products = db.query(Product).join(Order).group_by(Product.id).order_by(
                func.count(Order.id).desc()
            ).limit(5).all()
            
            # Si aucun produit populaire n'est trouvé, utiliser les produits avec réduction
            if not popular_products:
                popular_products = db.query(Product).join(Banner).filter(
                    Banner.discountPercent > 0
                ).order_by(desc(Banner.discountPercent)).limit(5).all()
            
            # Si toujours aucun produit, utiliser les produits les plus récents
            if not popular_products:
                popular_products = db.query(Product).order_by(
                    desc(Product.created_at)
                ).limit(5).all()
            
            # Construire les recommandations
            recommendations = []
            for product in popular_products:
                recommendations.append({
                    'product_id': product.id,
                    'name': product.name,
                    'price': product.price,
                    'type': 'popular',
                    'reason': 'Produits populaires que vous pourriez aimer'
                })
            
            return recommendations
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la génération des recommandations de repli : {e}")
            return []
    
    def generate_recommendations(self, profile: UserPreferenceProfile, interest_level: str, db: Session) -> List[Dict]:
        """
        Génère des recommandations personnalisées pour l'utilisateur
        
        :param profile: Profil de préférences de l'utilisateur
        :param interest_level: Niveau d'intérêt prédit
        :param db: Session de base de données SQLAlchemy
        :return: Liste de recommandations
        """
        try:
            recommendations = []
            already_seen_products = profile.preferred_product_ids or []
            
            # Nombre de recommandations souhaitées
            target_recommendations = 6
            
            # Recommandations basées sur la catégorie préférée (30% des recommandations)
            if profile.most_purchased_category_id:
                category_products = db.query(Product).filter(
                    Product.category_id == profile.most_purchased_category_id,
                    Product.id.notin_(already_seen_products)
                ).order_by(desc(Product.rating), desc(Product.created_at)).limit(2).all()
                
                for product in category_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'category_based',
                        'reason': 'Basé sur votre catégorie préférée'
                    })
            
            # Recommandations basées sur le niveau d'engagement (70% des recommandations)
            if interest_level == 'High':
                # Pour les utilisateurs très engagés, recommander des produits premium et nouveaux
                premium_products = db.query(Product).filter(
                    Product.price > 100,  # Seuil "premium"
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(desc(Product.created_at)).limit(2).all()
                
                for product in premium_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'premium',
                        'reason': 'Produits premium qui pourraient vous intéresser'
                    })
                
                # Ajouter des produits nouveaux (dernier mois)
                one_month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
                new_products = db.query(Product).filter(
                    Product.created_at >= one_month_ago,
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(desc(Product.created_at)).limit(2).all()
                
                for product in new_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'new_arrival',
                        'reason': 'Nouveautés qui viennent d\'arriver'
                    })
                    
            elif interest_level == 'Medium':
                # Pour les utilisateurs moyennement engagés, recommander des produits populaires et bien notés
                popular_products = db.query(Product).join(Order).group_by(Product.id).order_by(
                    func.count(Order.id).desc()
                ).filter(
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).limit(2).all()
                
                for product in popular_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'popular',
                        'reason': 'Produits populaires que d\'autres clients ont appréciés'
                    })
                
                # Ajouter des produits bien notés
                rated_products = db.query(Product).filter(
                    Product.rating > 4,
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(desc(Product.rating), desc(Product.nb_rating)).limit(2).all()
                
                for product in rated_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'highly_rated',
                        'reason': 'Produits très bien notés par notre communauté'
                    })
                    
            else:  # Low
                # Pour les utilisateurs peu engagés, recommander des produits à prix réduit et accessibles
                discount_products = db.query(Product).join(Banner).filter(
                    Banner.discountPercent > 0,
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(desc(Banner.discountPercent)).limit(3).all()
                
                for product in discount_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'discount',
                        'reason': 'Offres spéciales pour vous'
                    })
                
                # Ajouter des produits à bas prix
                affordable_products = db.query(Product).filter(
                    Product.price < 50,  # Seuil "abordable"
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(Product.price).limit(2).all()
                
                for product in affordable_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'affordable',
                        'reason': 'Produits à petits prix'
                    })
            
            # Si nous n'avons pas assez de recommandations, ajouter des produits généraux
            if len(recommendations) < target_recommendations:
                remaining = target_recommendations - len(recommendations)
                additional_products = db.query(Product).filter(
                    Product.id.notin_(already_seen_products + [rec['product_id'] for rec in recommendations])
                ).order_by(func.random()).limit(remaining).all()
                
                for product in additional_products:
                    recommendations.append({
                        'product_id': product.id,
                        'name': product.name,
                        'price': product.price,
                        'type': 'general',
                        'reason': 'Vous pourriez également aimer'
                    })
            
            return recommendations
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la génération des recommandations : {e}")
            return self._get_fallback_recommendations(db, profile.user_id)
    
    def save_model(self, filepath=None):
        """
        Sauvegarde le modèle entraîné
        
        :param filepath: Chemin de sauvegarde du modèle (optionnel)
        """
        if self.model is None:
            self.logger.warning("Aucun modèle à sauvegarder")
            return False
        
        filepath = filepath or self.model_filepath
        
        try:
            # Sauvegarder le modèle
            joblib.dump(self.model, filepath)
            
            # Sauvegarder également les métadonnées
            metadata = {
                'training_time': self.last_training_time.isoformat() if self.last_training_time else None,
                'performance': self.model_performance
            }
            
            metadata_filepath = f"{os.path.splitext(filepath)[0]}_metadata.joblib"
            joblib.dump(metadata, metadata_filepath)
            
            self.logger.info(f"Modèle sauvegardé à {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde du modèle : {e}")
            return False
    
    def load_model(self, filepath=None):
        """
        Charge un modèle préentraîné
        
        :param filepath: Chemin du modèle à charger (optionnel)
        :return: True si le chargement a réussi, False sinon
        """
        filepath = filepath or self.model_filepath
        
        try:
            # Charger le modèle
            self.model = joblib.load(filepath)
            
            # Tenter de charger les métadonnées
            try:
                metadata_filepath = f"{os.path.splitext(filepath)[0]}_metadata.joblib"
                metadata = joblib.load(metadata_filepath)
                
                if 'training_time' in metadata:
                    self.last_training_time = datetime.datetime.fromisoformat(metadata['training_time'])
                
                if 'performance' in metadata:
                    self.model_performance = metadata['performance']
                
            except Exception as e:
                self.logger.warning(f"Impossible de charger les métadonnées du modèle : {e}")
            
            self.logger.info(f"Modèle chargé depuis {filepath}")
            return True
        except Exception as e:
            self.logger.warning(f"Modèle non trouvé ou erreur de chargement : {e}")
            return False

# Initialiser le prédicteur
predictor = UserInterestPredictor()