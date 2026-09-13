from app.core.config import load_yaml

def public_configuration():
    w=load_yaml('warehouse.yaml'); r=load_yaml('robot.yaml')
    return {'warehouse':w.get('warehouse',{}),'slotting':w.get('slotting',{}),'robot':r.get('robot',{})}
