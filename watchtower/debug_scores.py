from lib.benchmark.data_generator import BenchmarkDataGenerator
from lib.benchmark.detection_systems.fds_single_layer import FDSSingleLayerSystem
from lib.benchmark.detection_systems.fds_two_layer import FDSTwoLayerSystem
from lib.benchmark.scenario import ScenarioType
from lib.benchmark.feature_extractor import extract_features

gen = BenchmarkDataGenerator()
sl = FDSSingleLayerSystem()
tl = FDSTwoLayerSystem()

sybil = gen.generate_sybil_attack()
flash = gen.generate_flash_loan_attack()
camo = gen.generate_camouflage_attack()

for name, sc in [("Sybil", sybil), ("Flash Loan", flash), ("Camouflage", camo)]:
    print(f"\n--- {name} ---")
    
    features = extract_features(sc)
    print(features)
    
    # SL Details
    print("SL:")
    prediction, applied_fpr, applied_threshold = sl._run_detection_algorithms(sc)
    print(sl._scorer.score(features), sl._check_simple_threshold(sc), prediction)
    
    # TL Details
    print("TL:")
    if tl._is_macro_transaction(sc):
        tl_macro = tl._detect_macro_layer(sc, features)
        print("Macro:", tl._scorer.score(features), tl._check_signature_validity(sc), tl._check_strict_threshold(sc), tl_macro)
    else:
        tl_micro = tl._detect_micro_layer(sc, features)
        print("Micro:", tl._scorer.score(features), tl_micro)
