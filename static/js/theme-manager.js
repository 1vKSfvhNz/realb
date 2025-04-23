/**
 * theme-manager.js
 * Module de gestion des thèmes (mode clair/sombre) pour Real Black
 * Créé le: 23 avril 2025
 */

(function() {
    // Styles pour le mode sombre
    const darkModeStyles = `
    body.dark-mode {
      background-color: #121212;
      color: #e0e0e0;
    }
    
    body.dark-mode .bg-white {
      background-color: #1f1f1f !important;
    }
    
    body.dark-mode .bg-gray-100 {
      background-color: #121212 !important;
    }
    
    body.dark-mode .text-gray-900 {
      color: #e0e0e0 !important;
    }
    
    body.dark-mode .text-gray-600, 
    body.dark-mode .text-gray-400 {
      color: #a0a0a0 !important;
    }
    
    body.dark-mode .border-gray-200,
    body.dark-mode .border-gray-800,
    body.dark-mode .border-b {
      border-color: #333333 !important;
    }
  
    body.dark-mode .bg-primary {
      background-color: #000000 !important;
    }
    
    body.dark-mode .bg-secondary {
      background-color: #0a0a0a !important;
    }
    
    body.dark-mode .bg-gray-900 {
      background-color: #000000 !important;
    }
    
    body.dark-mode .prose {
      color: #e0e0e0;
    }
    
    body.dark-mode .shadow-md,
    body.dark-mode .shadow-lg {
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.8), 0 2px 4px -1px rgba(0, 0, 0, 0.9);
    }
    
    body.dark-mode input, 
    body.dark-mode textarea, 
    body.dark-mode select {
      background-color: #2d2d2d !important;
      color: #e0e0e0 !important;
      border-color: #444444 !important;
    }
  
    #theme-toggle {
      position: fixed;
      top: 6rem;
      right: 1.5rem;
      width: 3rem;
      height: 3rem;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background-color: #4f46e5;
      color: white;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      z-index: 40;
      transition: all 0.3s ease;
      cursor: pointer;
      opacity: 1;
      visibility: visible;
    }
  
    #theme-toggle:hover {
      background-color: #4338ca;
    }
    
    @media (max-width: 640px) {
      #theme-toggle {
        top: auto;
        bottom: 5rem;
      }
    }
    `;
  
    /**
     * Initialiser le gestionnaire de thème
     */
    function initThemeManager() {
      // Créer et injecter la feuille de style
      const styleElement = document.createElement('style');
      styleElement.id = 'dark-mode-styles';
      styleElement.textContent = darkModeStyles;
      document.head.appendChild(styleElement);
      
      // Créer le bouton de bascule
      const toggleButton = document.createElement('button');
      toggleButton.id = 'theme-toggle';
      toggleButton.setAttribute('aria-label', 'Changer de thème');
      toggleButton.innerHTML = '<i class="fas fa-moon"></i>';
      document.body.appendChild(toggleButton);
      
      // Vérifier la préférence de l'utilisateur
      const isDarkMode = localStorage.getItem('realblack-dark-mode') === 'true';
      
      // Appliquer le mode initial
      if (isDarkMode) {
        document.body.classList.add('dark-mode');
        toggleButton.innerHTML = '<i class="fas fa-sun"></i>';
        changeLogoIcons('icon_w');
      } else {
        document.body.classList.remove('dark-mode');
        toggleButton.innerHTML = '<i class="fas fa-moon"></i>';
        changeLogoIcons('icon_b');
      }
      
      // Gérer le clic sur le bouton
      toggleButton.addEventListener('click', function() {
        const isDarkModeNow = document.body.classList.toggle('dark-mode');
        localStorage.setItem('realblack-dark-mode', isDarkModeNow);
        
        // Mettre à jour l'icône du bouton et les logos
        if (isDarkModeNow) {
          toggleButton.innerHTML = '<i class="fas fa-sun"></i>';
          changeLogoIcons('icon_w');
        } else {
          toggleButton.innerHTML = '<i class="fas fa-moon"></i>';
          changeLogoIcons('icon_b');
        }
      });
    }
    
    /**
     * Changer toutes les instances des icônes de logo
     * @param {string} mode - Mode actuel ('dark' ou 'light')
     */
    function changeLogoIcons(mode) {
      const logoImages = document.querySelectorAll('img[src*="icon_"]');
      
      // Déterminer le type d'icône en fonction du mode
      const iconType = mode === 'dark' ? 'icon_b' : 'icon_w';
      
      logoImages.forEach(img => {
        const currentSrc = img.getAttribute('src');
        // Remplacer le nom du fichier tout en préservant le chemin
        const newSrc = currentSrc.replace(/icon_[bw]/, iconType);
        img.setAttribute('src', newSrc);
      });
    }
  
    // Si le DOM est déjà chargé, initialiser immédiatement
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initThemeManager);
    } else {
      initThemeManager();
    }
})();