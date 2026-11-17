# Synthetic customer identities and market-oriented samples, not a vehicle catalogue.
# Each vehicle tuple lists make, model, variant, fuel, transmission and body category.
PROFILES = {
    'bh': {
        'cities': ('Manama', 'Riffa', 'Muharraq'),
        'timezone': 'Asia/Bahrain',
        'customers': ('Mariam Al Sayed', 'Hassan Jassim', 'Noor Salman', 'Ali Abbas'),
        'vehicles': (
            ('Toyota', 'Camry', 'LE', 'petrol', 'at', 'car'),
            ('Nissan', 'Sunny', 'SV', 'petrol', 'cvt', 'car'),
            ('Hyundai', 'Tucson', 'GL', 'petrol', 'at', 'suv'),
            ('Kia', 'Sportage', 'LX', 'petrol', 'at', 'suv'),
        ),
        'prices': (32, 12, 9),
    },
    'sa': {
        'cities': ('Riyadh', 'Jeddah', 'Dammam'),
        'timezone': 'Asia/Riyadh',
        'customers': ('Fahad Al Harbi', 'Noura Al Qahtani', 'Saad Al Mutairi', 'Hessa Al Zahrani'),
        'vehicles': (
            ('Toyota', 'Hilux', 'GLX', 'diesel', 'manual', 'commercial'),
            ('Hyundai', 'Accent', 'Smart', 'petrol', 'at', 'car'),
            ('Nissan', 'Patrol', 'SE', 'petrol', 'at', 'suv'),
            ('Toyota', 'Land Cruiser', 'GXR', 'petrol', 'at', 'suv'),
        ),
        'prices': (320, 120, 85),
    },
    'ae': {
        'cities': ('Dubai', 'Abu Dhabi', 'Sharjah'),
        'timezone': 'Asia/Dubai',
        'customers': ('Aisha Al Mazrouei', 'Omar Nasser', 'Sara Rahman', 'Zayed Al Mansoori'),
        'vehicles': (
            ('Nissan', 'Patrol', 'LE', 'petrol', 'at', 'suv'),
            ('Toyota', 'Corolla', 'XLI', 'petrol', 'cvt', 'car'),
            ('Mitsubishi', 'Pajero', 'GLS', 'petrol', 'at', 'suv'),
            ('Lexus', 'RX', '350h', 'hybrid', 'cvt', 'suv'),
        ),
        'prices': (310, 110, 80),
    },
    'in': {
        'cities': ('Kochi', 'Thrissur', 'Kozhikode'),
        'timezone': 'Asia/Kolkata',
        'state_xmlid': 'base.state_in_kl',
        'sale_tax_template': 'sgst_sale_18',
        'customers': ('Anjali Menon', 'Rahul Nair', 'Meera Pillai', 'Arjun Varma'),
        'vehicles': (
            ('Maruti Suzuki', 'Swift', 'VXi', 'petrol', 'manual', 'car'),
            ('Tata', 'Nexon', 'Creative', 'diesel', 'manual', 'suv'),
            ('Mahindra', 'Scorpio-N', 'Z8', 'diesel', 'at', 'suv'),
            ('Hyundai', 'Creta', 'SX', 'petrol', 'cvt', 'suv'),
        ),
        'prices': (2400, 950, 650),
    },
}
